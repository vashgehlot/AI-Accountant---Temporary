// What needs the person on the AI review page, as one list of cards: a card for each row with a warning or an error,
// one for each document with a problem, and one for a suggestion or a question that belongs on neither. Kept apart
// from the network so node --test can run it.
import type { Issue } from './api'
import type { Decision, Question } from './chat.ts'
import { formatMoney } from './chat.ts'
import { dayMonth } from './clientRules.ts'
import type { SavedRow } from './clients'
import { documentProblems, issueTitle, leftOut, rowIssues } from './ledger.ts'
import type { ReviewDetail } from './reviews.ts'

export interface TodoCard {
  key: string                  // 'row:7', 'doc:7', or 'q:<question>' / 's:<decision>' for a card of its own
  kind: 'row' | 'document' | 'other'
  row: SavedRow | null         // null only when it names no row, or none that is in the year's rows
  tag: string                  // 'Account', 'Recorded twice', …, 'Document total', 'Question', 'Suggestion'
  title: string                // the row as a person knows it, the document's file, or the question itself
  issues: Issue[]              // warnings and errors, errors first
  suggestions: Decision[]      // changes waiting for the person to apply
  questions: Question[]        // questions still to answer
  waiting: boolean             // nothing on it but questions answered "I don't have it" or "Not sure"
}

// The family of each issue code, as FAMILIES in ledgersync/agent/tools.py groups them, by the name a card is tagged
// with. Any other code is 'Other'.
const TAGS: Record<string, string[]> = {
  Account: ['account_unclear', 'unusual_account', 'asset_check', 'should_be_asset', 'small_asset', 'whose_account',
            'meal_check', 'sundry_check', 'claim_note', 'account_fact', 'account_choice', 'small_items_add_up'],
  'Recorded twice': ['booked_twice', 'duplicate_document', 'total_mismatch', 'possible_duplicate', 'claim_receipts_unclear'],
  Date: ['date_missing', 'date_conflict', 'date_out_of_period', 'before_first_year', 'file_date'],
  'VAT across items': ['mixed_items', 'vat_rate_mismatch'],
  'VAT not booked': ['vat_not_booked', 'not_vat_invoice'],
  'Records disagree': ['amount_conflict', 'claim_vat'],
  Documents: ['not_booked', 'open_document', 'no_payroll', 'needs_document', 'document_wanted', 'not_claimed', 'hotel_vat'],
}
const TAG_OF = new Map(Object.entries(TAGS).flatMap(([tag, codes]) => codes.map(code => [code, tag] as const)))
export const tagOf = (code: string): string => TAG_OF.get(code) ?? 'Other'

const whatOf = (row: SavedRow): string =>
  [row.description, row.date ? dayMonth(row.date) : 'no date', formatMoney(row.gross)].join(', ')

const errorsFirst = (issues: Issue[]): Issue[] =>
  [...issues.filter(i => i.severity === 'error'), ...issues.filter(i => i.severity === 'warning')]

// 0 a card with an error, 1 one with a question to answer, 2 one with a suggestion, 3 the rest, 4 waiting.
const rank = (card: TodoCard): number =>
  card.waiting ? 4
    : card.issues.some(i => i.severity === 'error') ? 0
      : card.questions.some(q => q.status === 'open') ? 1
        : card.suggestions.length ? 2 : 3

// The cards, in the order they are listed: by rank, then by the row's date (undated and row-less last). A suggestion
// or a question goes on the card of the first of its rows that has one (the row's own, else that of the document
// whose problem the row carries), else on a card of its own, named by the row, which two about the same row share.
// fileOf names a document.
export function todoCards(rows: SavedRow[], suggestions: Decision[], questions: Question[],
                          fileOf: (row: SavedRow) => string): TodoCard[] {
  const cards: TodoCard[] = []
  const blank = () => ({ suggestions: [] as Decision[], questions: [] as Question[], waiting: false })
  for (const row of rows) {
    if (leftOut(row)) continue
    const issues = errorsFirst(rowIssues(row))
    if (issues.length) cards.push({ ...blank(), key: `row:${row.id}`, kind: 'row', row, tag: tagOf(issues[0].code), title: whatOf(row), issues })
  }
  for (const { row, issue } of documentProblems(rows)) {
    cards.push({ ...blank(), key: `doc:${row.id}`, kind: 'document', row, tag: 'Document total', title: fileOf(row), issues: [issue] })
  }

  const cardFor = (rowIds: number[], own: () => Pick<TodoCard, 'key' | 'tag' | 'title'>): TodoCard => {
    const onRow = rowIds.map(id => cards.find(c => c.kind === 'row' && c.row?.id === id)).find(c => c)
    if (onRow) return onRow
    const onDocument = cards.find(c => c.kind === 'document' && rowIds.some(id => c.row?.id === id))
    if (onDocument) return onDocument
    const row = rowIds.map(id => rows.find(r => r.id === id)).find(r => r) ?? null
    const shared = row && cards.find(c => c.kind === 'other' && c.row?.id === row.id)
    if (shared) return shared
    const made: TodoCard = { ...blank(), ...own(), kind: 'other', row, issues: [] }
    if (row) made.title = whatOf(row)
    cards.push(made)
    return made
  }
  for (const q of questions) {
    cardFor(q.row_ids, () => ({ key: `q:${q.id}`, tag: 'Question', title: q.text })).questions.push(q)
  }
  for (const s of suggestions) {
    cardFor(s.row_ids, () => ({ key: `s:${s.id}`, tag: 'Suggestion', title: s.rule.replace(/^R\d+\s+/, '') })).suggestions.push(s)
  }
  for (const card of cards) {
    card.waiting = !card.issues.length && !card.suggestions.length && card.questions.every(q => q.status === 'waiting')
  }
  const date = (card: TodoCard) => card.row?.date ?? '9999'
  return cards.sort((a, b) => rank(a) - rank(b) || date(a).localeCompare(date(b)) || a.key.localeCompare(b.key))
}

// How many cards need the person: all but those only waiting on something they don't have yet.
export const needCount = (cards: TodoCard[]): number => cards.filter(c => !c.waiting).length

// Every suggestion on the list, for Apply all.
export const waitingSuggestions = (cards: TodoCard[]): Decision[] => cards.flatMap(c => c.suggestions)

// The questions still to answer, each once: the runs' (newest run's first), then the rest of the year's own, which the
// books ask of themselves (a date, the opening balances, a bad debt, missing paperwork) and are answered here too.
export function openQuestions(runs: ReviewDetail[], asked: Question[] = [], yearStart?: string): Question[] {
  const found = new Map<string, Question>()
  const keep = (q: Question) => { if (q.status !== 'resolved' && !found.has(q.id)) found.set(q.id, q) }
  for (const run of runs) run.questions.forEach(keep)
  asked.filter(q => q.year_start === yearStart).forEach(keep)
  return [...found.values()]
}

// ─── The queue's groups ──────────────────────────────────────────────────────

// Where a card sits in the queue, in the order of rank: an error, a question, a suggestion, a warning, and last the
// cards only waiting on something the person doesn't have yet.
export type QueueGroup = 'fix' | 'question' | 'suggestion' | 'check' | 'waiting'
const GROUPS: QueueGroup[] = ['fix', 'question', 'suggestion', 'check', 'waiting']
export const GROUP_LABELS: Record<QueueGroup, { title: string; note: string }> = {
  fix: { title: 'Must fix', note: 'stops the books being posted' },
  question: { title: 'Questions', note: 'the AI needs an answer' },
  suggestion: { title: 'Suggestions', note: 'changes to apply or leave' },
  check: { title: 'To check', note: 'warnings, one by one' },
  waiting: { title: 'Waiting on you', note: "answered: not to hand yet" },
}

export const groupOf = (card: TodoCard): QueueGroup => GROUPS[rank(card)]

// The cards by group, in the queue's order; a group with no card is left out.
export const queueGroups = (cards: TodoCard[]): { group: QueueGroup; cards: TodoCard[] }[] =>
  GROUPS.map(group => ({ group, cards: cards.filter(c => groupOf(c) === group) })).filter(g => g.cards.length)

// What kind of thing a card is about: its first issue's title, or its tag ("Question", "Suggestion") when it has none.
export const cardKind = (card: TodoCard): string => (card.issues.length ? issueTitle(card.issues[0].code) : card.tag)

// The warnings, folded by kind to be worked one by one: the kind with most cards first, then by name.
export function checkKinds(cards: TodoCard[]): { kind: string; cards: TodoCard[] }[] {
  const kinds = new Map<string, TodoCard[]>()
  for (const card of cards.filter(c => groupOf(c) === 'check')) {
    kinds.set(cardKind(card), [...(kinds.get(cardKind(card)) ?? []), card])
  }
  return [...kinds.entries()].map(([kind, list]) => ({ kind, cards: list }))
    .sort((a, b) => b.cards.length - a.cards.length || a.kind.localeCompare(b.kind, 'en-GB'))
}

// How many have been settled since the page opened: the count then less the count now, never below nothing (a review
// can add cards while the person works).
export const doneSince = (first: number | null, now: number): number => (first === null ? 0 : Math.max(0, first - now))

// Where the one-by-one stepper is: on its card wherever that card now is in the list, or, once it is settled and
// gone, on the card that took its place (the one before, if it was the last).
export function stepAt(cards: { key: string }[], key: string | null, at: number): number {
  const found = key === null ? -1 : cards.findIndex(c => c.key === key)
  return found >= 0 ? found : Math.max(0, Math.min(at, cards.length - 1))
}
