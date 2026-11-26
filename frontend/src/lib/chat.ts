// The accountant chat (design of 2026-11-02): its threads, the result a turn ends with, the questions it
// asks and the posted trial balance, and the calls that send a message (streamed back as SSE) and answer a question.
// Paths go through the Next rewrite, like every other call in api.ts. The pure functions are tested in chat.test.ts.
import { ApiError, errorFrom, request, type TrialBalanceLine, type TrialBalanceResult } from './api.ts'
import { longDate } from './ledger.ts'

// What the Overview's "N things need you" link asks in a new chat, so the open items show as cards in the reply.
export const ATTENTION = 'What needs my attention?'
// The chat about what needs attention, on the year named (the year whose questions wait) or, with none, the one the
// app picks: the earliest open year with questions waiting.
// Where the questions waiting in a year are answered: its AI review list, with no chat and no model call.
export const questionsHref = (clientId: number, yearStart: string) => `/clients/${clientId}/${yearStart}/ai-review`

export const attentionHref = (clientId: number, yearStart?: string) =>
  `/chat?client=${clientId}${yearStart ? `&year=${yearStart}` : ''}&ask=${encodeURIComponent(ATTENTION)}`

// The questions waiting for an answer (open or waiting), counted for the year on show (here) and for each other year
// that has some, in the order of the years.
export function waitingByYear(questions: Question[], years: { start: string; label: string }[], shown: string):
    { here: number; elsewhere: { start: string; label: string; count: number }[] } {
  const counts = new Map<string, number>()
  for (const q of questions) if (q.status !== 'resolved') counts.set(q.year_start, (counts.get(q.year_start) ?? 0) + 1)
  return {
    here: counts.get(shown) ?? 0,
    elsewhere: years.filter(y => y.start !== shown && counts.has(y.start))
                    .map(y => ({ start: y.start, label: y.label, count: counts.get(y.start)! })),
  }
}

// Money is a string everywhere below, like the rest of the API.
export interface ChatThread {
  id: string
  client_id: number
  year_start: string         // the client's year the chat works on: "2026-04-01"
  title: string              // "New chat" until the first message
  created_at: string
  updated_at: string
}

export interface Evidence {
  upload_id: number
  upload_name: string
  quote: string
}

// One thing the agent (or the rules, or a person's answer) did to the books, as the decisions log keeps it.
export interface Decision {
  id: string
  client_id: number
  thread_id: string | null
  year_start: string
  action: string
  rule: string               // "R2 Duplicate: kept the receipt"
  status: 'applied' | 'refused' | 'suggested'
  trigger?: 'chat' | 'background'   // where it came from: a chat turn, or a background review
  row_ids: number[]
  evidence: Evidence[]
  reason: string
  before: Record<string, Record<string, unknown>>   // the changed fields of each row, keyed by its id
  after: Record<string, Record<string, unknown>>
  actor: string              // "agent:<model>", "user" or "rules"
  reverses: string | null
  created_at: string
  prev_hash: string
  hash: string
}

export type QuestionKind = 'date' | 'receipt_or_invoice' | 'vat_invoice' | 'payout_report' | 'payroll_report'
  | 'opening_prepayments' | 'opening_accruals' | 'opening_vat' | 'bad_debt' | 'other'

// A question for the person: open until answered, waiting when they have no answer yet, resolved once answered.
export interface Question {
  id: string
  client_id: number
  year_start: string
  row_ids: number[]
  kind: QuestionKind
  text: string               // "When was this taxi?"
  why: string                // "£50 or more, so I need ..."
  source: 'rules' | 'agent'
  status: 'open' | 'waiting' | 'resolved'
  answer: string | null      // "I don't have it", "Not sure", or the answer given
  created_at: string
  resolved_at: string | null
  offer?: Offer | null       // an answer the agent filled in from what the person said, to change or confirm
}

// Where part of an offered answer comes from: the person's words, one of the client's documents (for the line
// "line:<n>" or the "date" it backs, with how a figure was worked out), or the question's own amount or date.
export interface OfferSource {
  kind: 'said' | 'document' | 'question'
  quote?: string
  upload_id?: number | null
  upload_name?: string
  for?: string | null
  working?: string
}

export interface Offer {
  answer: { kind: 'split'; lines: { account: string; amount: string }[] } | { kind: 'write_off'; date?: string | null }
  sources: OfferSource[]
  reason: string
  thread_id: string
  offered_at: string
  offered_by: string
}

export interface SuspenseItem {
  row_id: number
  description: string
  gross: string
  needs: 'receipt_or_invoice' | 'vat_invoice' | null   // null once the row is no longer held
}

// The trial balance of the posted ledger, with the rows held in Suspense among it.
export interface PostedTrialBalance extends TrialBalanceResult {
  suspense: SuspenseItem[]
  unposted_changes: number   // rows changed since they were posted
  problems: string[]         // what is wrong with the posted books, in words
}

export interface PostResult {
  batch_id: string | null    // null when the posting wrote nothing
  entries_added: number
  reversals_added: number
  total_debits: string
  total_credits: string
  problems: string[]         // why nothing was written, when the batch failed its checks
  left_out?: string[]        // rows needing a fix: not posted until they are fixed
}

// How a file the person added was read: shown as its chip, and kept with the message.
export interface FileRead {
  name: string
  state: 'done' | 'failed'
  rows: number | null
  reason: string | null
}

// What one turn did: what it sorted, the questions it raised or listed, and the books if it posted or showed them.
export interface TurnResult {
  sorted: Decision[]
  questions: Question[]
  trial_balance: PostedTrialBalance | null
  post: PostResult | null
}

// What answering a question did: that question as it now stands, and the effect on the books.
export interface AnswerResult {
  question: Question
  sorted: Decision[]
  trial_balance: PostedTrialBalance | null
  post: PostResult | null
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  files: FileRead[]
  result: TurnResult | null
}

// A thread as GET /api/chat/threads/{id} returns it: its messages so far, each with the result its turn ended with,
// and whether a turn is still running on it.
export interface ThreadDetail {
  thread: ChatThread
  messages: ChatMessage[]
  running: boolean
}

// The chat's title as its page shows it: the thread list's, which is loaded again when a turn ends, over the one the
// page loaded the chat with. The first message titles a chat, so a new chat's own copy still says "New chat".
export const currentTitle = (thread: ChatThread, threads: ChatThread[] | null): string =>
  threads?.find(t => t.id === thread.id)?.title ?? thread.title

// What a person is asked before a chat is deleted. The client's name is left out until the clients arrive.
export const deleteQuestion = (thread: Pick<ChatThread, 'title'>, clientName: string): string =>
  `Delete the chat "${thread.title}"${clientName ? ` for ${clientName}` : ''}?\n\n` +
  "The client's books keep everything this chat did; only the conversation goes. This cannot be undone."

// The longest title the API keeps for a chat.
export const TITLE_MAX = 60

// The title to rename a chat to from what was typed, or null when there is nothing to rename: it is empty, or the
// title the chat already has.
export function newTitle(typed: string, current: string): string | null {
  const title = typed.trim().slice(0, TITLE_MAX).trim()
  return title && title !== current ? title : null
}

// Where the page goes once a chat is deleted: New chat when it was the open one, nowhere (null) otherwise.
export const afterDelete = (deletedId: string, openId: string | undefined): string | null =>
  deletedId === openId ? '/chat' : null

export const POLL_MS = 3000

// Whether a loaded chat is worth loading again: a turn runs on the server that this page did not send itself.
export const shouldPoll = (detail: Pick<ThreadDetail, 'running'>, ownTurnRunning: boolean) => detail.running && !ownTurnRunning

export type StepState = 'running' | 'done' | 'failed'

// A step of a turn. A step is sent again under its id as it changes ("Reading a.csv…" → "Read a.csv (12 rows)").
// A step about a file names it, so the file's chip can show how it went.
export interface Step {
  id: string
  text: string
  state: StepState
  file?: string
  rows?: number
  reason?: string
}

export type ChatError = { code: 'model_unavailable' | 'loop_limit' | string; message: string; steps?: number }

export type ChatEvent =
  | { type: 'status'; data: { text: string } }
  | { type: 'step'; data: Step }
  | { type: 'token'; data: { text: string } }
  | { type: 'result'; data: TurnResult }
  | { type: 'error'; data: ChatError }
  | { type: 'done'; data: Record<string, never> }

export type Answer = { kind: 'date'; date: string } | { kind: 'no_document' } | { kind: 'not_sure' }
  | { kind: 'without_document'; reason: string }   // book it with no VAT reclaimed: a person only, never the AI
  | { kind: 'split'; lines: { account: string; amount: string }[] }   // the costs an opening balance is released to
  | { kind: 'write_off'; date?: string }   // write the invoice off as a bad debt, by default when six months overdue

const EVENT_TYPES = new Set<string>(['status', 'step', 'token', 'result', 'error', 'done'])

// Parses SSE text that may stop anywhere: the events completed so far, and what is left over for the next chunk.
export function parseEvents(chunk: string, carry: string): { events: ChatEvent[]; carry: string } {
  const blocks = (carry + chunk).replace(/\r\n?/g, '\n').split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: ChatEvent[] = []
  for (const block of blocks) {
    let type = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon < 0 ? line : line.slice(0, colon)
      const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
      if (field === 'event') type = value
      else if (field === 'data') data.push(value)
    }
    if (!EVENT_TYPES.has(type) || !data.length) continue
    events.push({ type, data: JSON.parse(data.join('\n')) } as ChatEvent)
  }
  return { events, carry: rest }
}

const dayOf = (when: Date) => new Date(when.getFullYear(), when.getMonth(), when.getDate()).getTime()

// The thread list's groups, newest first in each, by the computer's own calendar; empty groups are left out.
export function groupThreads(threads: ChatThread[], now: Date):
    { label: 'Today' | 'Yesterday' | 'Earlier'; threads: ChatThread[] }[] {
  const today = dayOf(now)
  const yesterday = dayOf(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))
  const groups = { Today: [] as ChatThread[], Yesterday: [] as ChatThread[], Earlier: [] as ChatThread[] }
  const newest = [...threads].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  for (const t of newest) {
    const day = dayOf(new Date(t.updated_at))
    groups[day >= today ? 'Today' : day === yesterday ? 'Yesterday' : 'Earlier'].push(t)
  }
  return (['Today', 'Yesterday', 'Earlier'] as const)
    .filter(label => groups[label].length)
    .map(label => ({ label, threads: groups[label] }))
}

// How a question is answered: a date (or Not sure), a document (or I don't have it), or in words.
export function questionControl(q: Question): 'date' | 'upload' | 'split' | 'write_off' | 'text' {
  if (q.kind === 'date') return 'date'
  if (q.kind === 'opening_prepayments' || q.kind === 'opening_accruals' || q.kind === 'opening_vat') return 'split'
  if (q.kind === 'bad_debt') return 'write_off'
  if (['receipt_or_invoice', 'vat_invoice', 'payout_report', 'payroll_report'].includes(q.kind)) return 'upload'
  return 'text'
}

// What an opening balance question asks to be split, as a decimal string ("6558.46"), from its text; null for others.
export const openingAmount = (q: Question): string | null =>
  (q.kind === 'opening_vat' ? /is £([\d,]+\.\d{2}) (?:more|less)/ : /of £([\d,]+\.\d{2})/).exec(q.text)?.[1]
    .replace(/,/g, '') ?? null

// The lines' amounts added up in pence, as a decimal string; a line that isn't an amount counts as nothing.
export function splitTotal(lines: { amount: string }[]): string {
  const pence = lines.reduce((sum, l) => {
    const m = /^(\d+)(?:\.(\d{1,2}))?$/.exec(l.amount.trim().replace(/,/g, ''))
    return m ? sum + Number(m[1]) * 100 + Number((m[2] ?? '').padEnd(2, '0')) : sum
  }, 0)
  return `${Math.floor(pence / 100)}.${String(pence % 100).padStart(2, '0')}`
}

// Whether the question is a purchase held in Suspense for its receipt or invoice, which a person can book without it
// (no VAT reclaimed) when there is none to be had. A payout or payroll report books other rows, so it can't be skipped.
export const canBookWithout = (q: Question) => q.kind === 'receipt_or_invoice' || q.kind === 'vat_invoice'

// "R2" from "R2 Duplicate: kept the receipt"; '' for a rule without a number.
export const ruleBadge = (d: Decision): string => /^R\d+\b/.exec(d.rule)?.[0] ?? ''

// "£1,412.68" and "-£1,412.68", from the exact decimal string, so no pence are lost to floating point.
export function formatMoney(s: string): string {
  const negative = s.trim().startsWith('-')
  const [whole, fraction = ''] = s.trim().replace(/^[-+]/, '').split('.')
  const pence = fraction.length > 2 ? Number(`0.${fraction}`).toFixed(2).slice(2) : fraction.padEnd(2, '0')
  const pounds = (whole.replace(/^0+(?=\d)/, '') || '0').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const zero = /^[0,]+$/.test(pounds) && pence === '00'
  return `${negative && !zero ? '-' : ''}£${pounds}.${pence}`
}

const FIELD_NAMES: Record<string, string> = {
  gross: 'Amount', vat: 'VAT', net: 'Net', date: 'Date', description: 'Description', counterparty: 'Payee',
  account_code: 'Account', direction: 'Direction', excluded: 'Removed from the books', document_type: 'Document',
}
const MONEY_FIELDS = new Set(['gross', 'vat', 'net', 'vat_posted', 'amount'])

const fieldValue = (field: string, value: unknown): string => {
  if (value == null || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (MONEY_FIELDS.has(field)) return formatMoney(String(value))
  if (field === 'date' && /^\d{4}-\d{2}-\d{2}$/.test(String(value))) return longDate(String(value))
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

const fieldName = (field: string) => FIELD_NAMES[field] ?? field.charAt(0).toUpperCase() + field.slice(1).replace(/_/g, ' ')

// The decisions behind a row's Agent badge: those of its decision ids that are loaded and weren't a person's (an undo
// is the person's). null when none of them is loaded, which the badge shows without a popover; [] when they are all
// a person's, which shows no badge.
export function agentDecisions(ids: string[], loaded: Map<string, Decision>): Decision[] | null {
  const found = ids.flatMap(id => loaded.get(id) ?? [])
  return found.length ? found.filter(d => d.actor !== 'user') : null
}

// A decision's before → after, one line per changed field of each row, in words.
export function changedFields(d: Decision): { row: number; field: string; before: string; after: string }[] {
  const rows = [...new Set([...Object.keys(d.before), ...Object.keys(d.after)])].sort((a, b) => Number(a) - Number(b))
  return rows.flatMap(row => {
    const before = d.before[row] ?? {}
    const after = d.after[row] ?? {}
    return [...new Set([...Object.keys(before), ...Object.keys(after)])].map(field => ({
      row: Number(row), field: fieldName(field), before: fieldValue(field, before[field]), after: fieldValue(field, after[field]),
    }))
  })
}

export type FileState = 'queued' | 'reading' | 'done' | 'failed'

const readLabel = (state: 'done' | 'failed', rows: number | null | undefined, reason: string | null | undefined) =>
  state === 'failed' ? (reason ? `Failed: ${reason}` : 'Failed') : rows == null ? 'Read' : `Read (${rows} ${rows === 1 ? 'row' : 'rows'})`

// What a file's chip says, from the latest step that names it.
export function fileStatus(name: string, steps: Step[]): { state: FileState; label: string } {
  const step = [...steps].reverse().find(s => s.file === name)
  if (!step) return { state: 'queued', label: 'Queued' }
  if (step.state === 'running') return { state: 'reading', label: 'Reading' }
  return { state: step.state, label: readLabel(step.state, step.rows, step.reason) }
}

// What a saved file's chip says, from how it was read.
export const readStatus = (f: FileRead): { state: FileState; label: string } =>
  ({ state: f.state, label: readLabel(f.state, f.rows, f.reason) })

// Whether a turn's result has anything to show.
export const hasResult = (r: TurnResult | null): r is TurnResult =>
  r != null && (r.sorted.length > 0 || r.questions.length > 0 || r.trial_balance != null || r.post != null)

// The items with every card for this question replaced by its current record.
export const withQuestion = <T extends { result: TurnResult | null }>(items: T[], q: Question): T[] =>
  items.map(item => item.result?.questions.some(c => c.id === q.id)
    ? { ...item, result: { ...item.result, questions: item.result.questions.map(c => (c.id === q.id ? q : c)) } }
    : item)

// Where a question stands, in words; null while it is open.
export function questionState(q: Question): string | null {
  if (q.status === 'open') return null
  if (q.status === 'resolved' && q.answer?.startsWith('Booked without a receipt')) return q.answer
  if (q.status === 'resolved') return q.answer ? `Answered: ${q.answer}` : 'Resolved'
  if (q.answer === "I don't have it") return q.kind === 'vat_invoice' ? 'Waiting for the VAT invoice' : 'Waiting for the receipt or invoice'
  if (q.answer === 'Not sure') return 'Waiting: not sure of the date yet'
  return `Waiting: ${q.answer}`
}

// What an answer did to the books, in one line; null when it changed nothing there.
export function effectLine(a: AnswerResult): string | null {
  if (a.post?.problems.length) return `Nothing was posted: ${a.post.problems.join(' ')}`
  if (!a.trial_balance) return null
  const held = a.trial_balance.suspense.length
  const suspense = held === 0 ? 'nothing in Suspense' : `${held} ${held === 1 ? 'item' : 'items'} in Suspense`
  const out = a.post?.left_out?.length ?? 0
  const left = out === 0 ? '' : ` · ${out} ${out === 1 ? 'row' : 'rows'} left out until ${out === 1 ? 'it is' : 'they are'} fixed`
  return `Posted · ${a.trial_balance.is_balanced ? 'balanced' : 'not balanced'} · ${suspense}${left}`
}

// The files a retry sends again: those not read the first time, each with its bank account. A file read once is
// saved to the client already, and sending it again would book it twice.
export function retryFiles(files: File[], bankAccounts: string[], steps: Step[]): { files: File[]; bankAccounts: string[] } {
  const keep = files.map((f, i) => [f, bankAccounts[i] ?? ''] as const).filter(([f]) => fileStatus(f.name, steps).state !== 'done')
  return { files: keep.map(([f]) => f), bankAccounts: keep.map(([, code]) => code) }
}

export const suspenseLabel = (needs: SuspenseItem['needs']) =>
  needs === 'vat_invoice' ? 'needs VAT invoice' : needs === 'receipt_or_invoice' ? 'needs receipt or invoice' : 'Suspense'

const STATEMENT_TYPES = /\.(csv|ofx|qfx|qif|xls|xlsx)$/i

// Whether a file is likely a bank statement, so its chip offers the bank account it goes on.
export const looksLikeStatement = (name: string) => STATEMENT_TYPES.test(name) || /statement/i.test(name)

export const SUSPENSE = '9998'
const SHOWN_ACCOUNTS = 5

// The accounts the Posted part shows: the first five with a balance, and Suspense always, with how many are left.
export function shownAccounts(tb: PostedTrialBalance): { shown: TrialBalanceLine[]; more: number } {
  const used = tb.lines.filter(l => Number(l.debit) !== 0 || Number(l.credit) !== 0)
  const shown = used.slice(0, SHOWN_ACCOUNTS)
  const suspense = used.find(l => l.code === SUSPENSE)
  if (suspense && !shown.includes(suspense)) shown.push(suspense)
  return { shown, more: used.length - shown.length }
}

const WRITE = { 'X-LedgerSync': '1' }
const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json', ...WRITE }, body: JSON.stringify(body),
})

// All threads, or one client's.
export const listThreads = (clientId?: number) =>
  request<ChatThread[]>(clientId ? `/api/chat/threads?client_id=${clientId}` : '/api/chat/threads')
export const newThread = (clientId: number, yearStart?: string) =>
  request<ChatThread>('/api/chat/threads', json('POST', yearStart ? { client_id: clientId, year_start: yearStart } : { client_id: clientId }))
export const getThread = (id: string) => request<ThreadDetail>(`/api/chat/threads/${id}`)
// Gives a chat a new title. A chat a person has named keeps that name; only a "New chat" is titled by its first message.
export const renameThread = (id: string, title: string) =>
  request<ChatThread>(`/api/chat/threads/${id}`, json('PATCH', { title }))
// Deletes a chat and what the AI remembers of it; refused while a message runs on it. The client's books are not touched.
export const deleteThread = (id: string) => request<void>(`/api/chat/threads/${id}`, { method: 'DELETE', headers: WRITE })
export const stopRun = (id: string) =>
  request<unknown>(`/api/chat/threads/${id}/stop`, { method: 'POST', headers: WRITE })
// The client's open and waiting questions, from every chat on it.
export const clientQuestions = (clientId: number) => request<Question[]>(`/api/clients/${clientId}/questions`)
export const resetDemo = () => request<unknown>('/api/demo/reset', { method: 'POST', headers: WRITE }, 120_000)

export const answerQuestion = (threadId: string, questionId: string, answer: Answer) =>
  request<AnswerResult>(`/api/chat/threads/${threadId}/questions/${questionId}/answer`, json('POST', answer), 120_000)

export function uploadForQuestion(threadId: string, questionId: string, file: File): Promise<AnswerResult> {
  const data = new FormData()
  data.append('file', file)
  return request<AnswerResult>(`/api/chat/threads/${threadId}/questions/${questionId}/document`,
                                { method: 'POST', body: data, headers: WRITE }, 180_000)
}

// Sends a message with its files (bankAccounts[i] is the account files[i] goes on if it is a statement; '' for the
// client's first) and calls onEvent for each event until the stream ends. A refusal, such as a second message
// while one runs (409), throws ApiError with the API's reason.
export async function streamMessage(
  threadId: string,
  text: string,
  files: File[],
  bankAccounts: string[],
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const data = new FormData()
  data.append('text', text)
  files.forEach(f => data.append('files', f))
  bankAccounts.forEach(code => data.append('bank_accounts', code))
  const res = await fetch(`/api/chat/threads/${threadId}/messages`, { method: 'POST', body: data, headers: WRITE, signal })
    .catch((e: unknown) => {
      if (signal.aborted) throw e
      throw new ApiError('Super Accountant could not be reached. Try again in a moment; if it keeps happening, the person who runs it needs to check the server is up.', 'network')
    })
  if (!res.ok) throw await errorFrom(res)
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let carry = ''
  for (;;) {
    const { done, value } = await reader.read()
    const parsed = parseEvents(done ? decoder.decode() : decoder.decode(value, { stream: true }), carry)
    carry = parsed.carry
    parsed.events.forEach(onEvent)
    if (done) return
  }
}

// The agent's words as the chat shows them. It is told to write plain text, but a model still marks a phrase bold
// (**7400 Travel**) or a heading (## Options) now and then: the marks are dropped, the words kept.
export const plainReply = (text: string): string =>
  text.replace(/\*\*([^*\n]+)\*\*/g, '$1').replace(/^#{1,6}\s+/gm, '').replace(/`([^`\n]+)`/g, '$1')

// The split lines an offered answer fills the form with; null when nothing split is offered.
export function offerLines(q: Question): { account: string; amount: string }[] | null {
  const a = q.offer?.answer
  return a && a.kind === 'split' ? a.lines.map(l => ({ account: l.account, amount: l.amount })) : null
}

// The write-off date an offer gives; null for none (the default: when the six months end) or no offer.
export function offerDate(q: Question): string | null {
  const a = q.offer?.answer
  return a && a.kind === 'write_off' ? a.date ?? null : null
}

// What backs a part of the offer ("line:1", "date"): its own document quotes, and the question itself if it gave one.
export const sourcesFor = (q: Question, part: string): OfferSource[] =>
  (q.offer?.sources ?? []).filter(s => s.for === part || s.kind === 'question')

// For each line on the form, whether the person changed it from the offer (or added it).
export const changedLines = (offered: { account: string; amount: string }[], current: { account: string; amount: string }[]) =>
  current.map((l, n) => !offered[n] || offered[n].account !== l.account.trim() || offered[n].amount !== l.amount.trim())

// The form's lines when the question changes: an offer fills them in, unless the person has typed in them already.
export function nextLines(current: { account: string; amount: string }[], q: Question, touched: boolean) {
  const lines = offerLines(q)
  return lines && !touched ? lines : current
}

// Whether a line's figure is the question's own amount: so for a one-line split the offer backs with the question.
export const fromQuestion = (q: Question, line: number): boolean => {
  const lines = offerLines(q)
  return !!lines && lines.length === 1 && line === 1 && (q.offer?.sources ?? []).some(s => s.kind === 'question')
}
