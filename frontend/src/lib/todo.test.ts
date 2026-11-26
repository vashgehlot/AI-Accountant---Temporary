// Run with: npm test.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cardKind, checkKinds, doneSince, stepAt, GROUP_LABELS, groupOf, needCount, openQuestions, queueGroups, tagOf, todoCards, waitingSuggestions } from './todo.ts'
import type { Decision, Question } from './chat.ts'
import type { SavedRow } from './clients'
import type { ReviewDetail } from './reviews.ts'

type Severity = 'info' | 'warning' | 'error'
const issue = (code: string, severity: Severity = 'warning', more: object = {}) =>
  ({ code, message: `${code} said`, severity, related: [], ...more })
const row = (id: number, issues: ReturnType<typeof issue>[] = [], more: Partial<SavedRow> = {}): SavedRow => ({
  id, upload_id: 1, edited: false, original: null, date: '2026-10-12', description: 'Vodafone bill', direction: 'out',
  gross: '86.40', issues, ...more,
} as unknown as SavedRow)
const suggestion = (id: string, row_ids: number[], rule = 'R6 Account changed'): Decision => ({
  id, client_id: 1, thread_id: null, year_start: '2026-04-01', action: 'change_account', rule, status: 'suggested',
  trigger: 'background', row_ids, evidence: [], reason: 'why', before: {}, after: {}, actor: 'rules', reverses: null,
  created_at: '2026-11-04T10:42:00', prev_hash: '', hash: 'h',
} as unknown as Decision)
const question = (id: string, row_ids: number[], status: Question['status'] = 'open', text = 'When was this taxi?'): Question => ({
  id, client_id: 1, year_start: '2026-04-01', row_ids, kind: 'other', text, why: 'why', source: 'agent', status,
  answer: status === 'waiting' ? "I don't have it" : null, created_at: '2026-11-04T10:42:00', resolved_at: null,
})
const file = (r: SavedRow) => `file${r.upload_id}.xlsx, expense claim`
const keys = (cards: { key: string }[]) => cards.map(c => c.key)

test('a row with two warnings is one card, tagged by the first', () => {
  const cards = todoCards([row(1, [issue('unusual_account'), issue('date_missing')])], [], [], file)
  assert.equal(cards.length, 1)
  assert.deepEqual([cards[0].key, cards[0].kind, cards[0].tag, cards[0].issues.length], ['row:1', 'row', 'Account', 2])
  assert.equal(cards[0].title, 'Vodafone bill, 12 Oct, £86.40')
  assert.equal(cards[0].row?.id, 1)
})

test('an error names the card before a warning does, and an unknown code is Other', () => {
  const [card] = todoCards([row(1, [issue('unusual_account'), issue('vat_arithmetic', 'error')])], [], [], file)
  assert.equal(card.tag, 'Other')
  assert.deepEqual(card.issues.map(i => i.code), ['vat_arithmetic', 'unusual_account'])
})

test('a note alone, or a row left out, makes no card', () => {
  const rows = [row(1, [issue('asset_check', 'info')]), row(2, [issue('unusual_account')], { excluded: true }),
                row(3, [issue('unusual_account')], { superseded_by: 'D1' })]
  assert.deepEqual(todoCards(rows, [], [], file), [])
})

test('the sundry, refreshments and meal questions are Account cards', () => {
  for (const code of ['sundry_check', 'meal_check', 'account_fact', 'account_choice', 'small_items_add_up']) {
    const [card] = todoCards([row(1, [issue(code)])], [], [], file)
    assert.equal(card.tag, 'Account')
  }
})

test('a note is left off a card that has a warning', () => {
  const [card] = todoCards([row(1, [issue('asset_check', 'info'), issue('unusual_account')])], [], [], file)
  assert.deepEqual(card.issues.map(i => i.code), ['unusual_account'])
})

test('a document problem is a card named by its file', () => {
  const rows = [row(1, [issue('total_mismatch', 'warning', { about: 'document', difference: '457.20' })], { document_ref: 'claim' }),
                row(2, [], { document_ref: 'claim' })]
  const cards = todoCards(rows, [], [], file)
  assert.equal(cards.length, 1)
  assert.deepEqual([cards[0].key, cards[0].kind, cards[0].tag, cards[0].title], ['doc:1', 'document', 'Document total', 'file1.xlsx, expense claim'])
  assert.equal(cards[0].issues.length, 1)
})

test('a row with its own warning and its document’s problem is two cards', () => {
  const rows = [row(1, [issue('total_mismatch', 'warning', { about: 'document' }), issue('unusual_account')], { document_ref: 'claim' })]
  assert.deepEqual(keys(todoCards(rows, [], [], file)).sort(), ['doc:1', 'row:1'])
})

test('a suggestion and a question land on their row’s card', () => {
  const cards = todoCards([row(1, [issue('unusual_account')])], [suggestion('D1', [1])], [question('Q1', [9, 1])], file)
  assert.equal(cards.length, 1)
  assert.deepEqual([cards[0].suggestions.map(s => s.id), cards[0].questions.map(q => q.id)], [['D1'], ['Q1']])
})

test('a suggestion about the row that carries a document’s problem lands on the document’s card', () => {
  const rows = [row(1, [issue('total_mismatch', 'warning', { about: 'document' })], { document_ref: 'claim' }),
                row(2, [], { document_ref: 'claim' })]
  const cards = todoCards(rows, [suggestion('D1', [1])], [], file)
  assert.deepEqual(keys(cards), ['doc:1'])
  assert.deepEqual(cards[0].suggestions.map(s => s.id), ['D1'])
})

test('a question about another line of that document gets its own card, named by the line', () => {
  const rows = [row(1, [issue('total_mismatch', 'warning', { about: 'document' })], { document_ref: 'claim' }),
                row(2, [], { document_ref: 'claim', description: 'Uber' })]
  const cards = todoCards(rows, [], [question('Q1', [2])], file)
  assert.deepEqual(keys(cards), ['q:Q1', 'doc:1'])
  assert.equal(cards[0].title, 'Uber, 12 Oct, £86.40')
})

test('a question about a row with no problem gets its own card, named by the row', () => {
  const [card] = todoCards([row(5)], [], [question('Q1', [5])], file)
  assert.deepEqual([card.key, card.kind, card.tag, card.title, card.row?.id], ['q:Q1', 'other', 'Question', 'Vodafone bill, 12 Oct, £86.40', 5])
})

test('a question about a row left out of the books is still listed, named by the row', () => {
  const [card] = todoCards([row(5, [], { excluded: true })], [], [question('Q1', [5])], file)
  assert.deepEqual([card.key, card.row?.id], ['q:Q1', 5])
})

test('a question and a suggestion about the same row with no problem share a card', () => {
  const cards = todoCards([row(5)], [suggestion('D1', [5])], [question('Q1', [5])], file)
  assert.equal(cards.length, 1)
  assert.deepEqual([cards[0].tag, cards[0].suggestions.length, cards[0].questions.length], ['Question', 1, 1])
})

test('a question that names no row is titled by its text', () => {
  const [card] = todoCards([], [], [question('Q1', [], 'open', 'Is there a payroll report?')], file)
  assert.deepEqual([card.key, card.row, card.title, card.tag], ['q:Q1', null, 'Is there a payroll report?', 'Question'])
})

test('a suggestion whose row is gone is titled by its rule', () => {
  const [card] = todoCards([], [suggestion('D1', [99], 'R2 Duplicate: kept the receipt')], [], file)
  assert.deepEqual([card.key, card.row, card.title, card.tag], ['s:D1', null, 'Duplicate: kept the receipt', 'Suggestion'])
})

test('errors come first, then questions, then suggestions, then the rest by date, waiting last', () => {
  const rows = [
    row(1, [issue('unusual_account')], { date: '2026-10-20' }),
    row(2, [issue('unusual_account')], { date: '2026-10-05' }),
    row(3, [issue('unusual_account')], { date: '2026-10-25' }),
    row(4, [issue('unusual_account')], { date: '2026-10-28' }),
    row(5, [issue('vat_arithmetic', 'error')], { date: '2026-10-30' }),
    row(6, [issue('date_missing')], { date: null }),
    row(7),
  ]
  const cards = todoCards(rows, [suggestion('D1', [3])], [question('Q1', [4]), question('Q2', [7], 'waiting')], file)
  assert.deepEqual(keys(cards), ['row:5', 'row:4', 'row:3', 'row:2', 'row:1', 'row:6', 'q:Q2'])
})

test('a card with only a waiting question is waiting and not counted', () => {
  const cards = todoCards([row(1, [issue('unusual_account')]), row(7)], [], [question('Q2', [7], 'waiting')], file)
  assert.deepEqual(cards.map(c => c.waiting), [false, true])
  assert.equal(needCount(cards), 1)
})

test('a waiting question on a row with a problem leaves the card needing the person', () => {
  const [card] = todoCards([row(1, [issue('unusual_account')])], [], [question('Q2', [1], 'waiting')], file)
  assert.equal(card.waiting, false)
})

test('the same question in two runs is listed once; a resolved one is not', () => {
  const run = (questions: Question[]) => ({ questions } as unknown as ReviewDetail)
  const found = openQuestions([run([question('Q1', [1]), question('Q3', [2], 'resolved')]), run([question('Q1', [1]), question('Q2', [], 'waiting')])])
  assert.deepEqual(found.map(q => q.id), ['Q1', 'Q2'])
})

test("the books' own questions of the year join the runs' questions, each once", () => {
  // The agency run: the opening balances, the bad debt and the VAT difference could be answered only through a chat.
  const run = (questions: Question[]) => ({ questions } as unknown as ReviewDetail)
  const of = (q: Question, year: string) => ({ ...q, year_start: year })
  const asked = [of(question('Q1', [1]), '2023-04-01'), of(question('R1', []), '2023-04-01'),
                 of(question('R2', [], 'resolved'), '2023-04-01'), of(question('R3', []), '2024-04-01')]
  const found = openQuestions([run([question('Q1', [1])])], asked, '2023-04-01')
  assert.deepEqual(found.map(q => q.id), ['Q1', 'R1'])
})

test('waitingSuggestions lists each suggestion once', () => {
  const cards = todoCards([row(1, [issue('unusual_account')]), row(5)], [suggestion('D1', [1]), suggestion('D2', [5])], [], file)
  assert.deepEqual(waitingSuggestions(cards).map(s => s.id).sort(), ['D1', 'D2'])
})

test('a charge left off a claim is about documents, and an unclear set about a purchase recorded twice', () => {
  assert.equal(tagOf('not_claimed'), 'Documents')
  assert.equal(tagOf('hotel_vat'), 'Documents')   // a UK hotel stay waiting for the property's VAT invoice
  assert.equal(tagOf('claim_receipts_unclear'), 'Recorded twice')
})

// ─── The queue's groups ──────────────────────────────────────────────────────

test('each card falls in one group, errors before questions before suggestions before warnings', () => {
  const cards = todoCards([row(1, [issue('unusual_account')]), row(2, [issue('date_missing', 'error')])],
                          [suggestion('s', [9])], [question('q', [8])], file)
  assert.deepEqual(queueGroups(cards).map(g => [g.group, g.cards.length]),
                   [['fix', 1], ['question', 1], ['suggestion', 1], ['check', 1]])
  assert.equal(GROUP_LABELS.fix.title, 'Must fix')
})

test('a card only waiting on the person is in the last group', () => {
  const cards = todoCards([], [], [question('q', [8], 'waiting'), question('r', [7])], file)
  assert.deepEqual(cards.map(groupOf), ['question', 'waiting'])
  assert.deepEqual(queueGroups(cards).map(g => g.group), ['question', 'waiting'])
})

test('warnings are folded by kind, the biggest first; other groups are not', () => {
  const cards = todoCards([row(1, [issue('unusual_account')]), row(2, [issue('date_missing')]), row(3, [issue('date_missing')]),
                           row(4, [issue('date_missing', 'error')])], [], [], file)
  assert.deepEqual(checkKinds(cards).map(k => [k.kind, k.cards.length]),
                   [['No date', 2], ["Not this supplier's usual account", 1]])
})

test("a card's kind is its first issue's title, or its tag when it has none", () => {
  const cards = todoCards([row(1, [issue('date_missing')])], [suggestion('s', [9])], [], file)
  assert.deepEqual(cards.map(cardKind), ['Suggestion', 'No date'])   // a suggestion ranks before a warning
})

test('done since opening never goes below nothing', () => {
  assert.equal(doneSince(113, 108), 5)
  assert.equal(doneSince(100, 104), 0)
  assert.equal(doneSince(null, 3), 0)
})

test('the stepper stays on its card when cards before it come or go', () => {
  const cards = [{ key: 'a' }, { key: 'b' }, { key: 'c' }]
  assert.equal(stepAt(cards, 'b', 1), 1)
  assert.equal(stepAt([{ key: 'z' }, ...cards], 'b', 1), 2)   // a poll put a card before it
  assert.equal(stepAt([{ key: 'a' }, { key: 'c' }], 'b', 1), 1)  // settled: the next one takes its place
  assert.equal(stepAt([{ key: 'a' }], 'b', 1), 0)                // the last: the one before
  assert.equal(stepAt([], 'b', 1), 0)
  assert.equal(stepAt(cards, null, 0), 0)
})
