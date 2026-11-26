// Run with: npm test. A stubbed fetch stands in for the API.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ApiError } from './api.ts'
import {
  agentDecisions, answerQuestion, attentionHref, questionsHref, changedFields, effectLine, fileStatus, formatMoney, groupThreads, hasResult, looksLikeStatement, parseEvents,
  canBookWithout, openingAmount, questionControl, questionState, splitTotal, shouldPoll, readStatus, ruleBadge, retryFiles, shownAccounts, streamMessage, suspenseLabel, uploadForQuestion,
  waitingByYear, withQuestion, afterDelete, deleteQuestion, deleteThread, newTitle, renameThread,
  type AnswerResult, type ChatEvent, type ChatThread, type Decision, type PostResult, type PostedTrialBalance, type Question,
} from './chat.ts'

const thread = (id: string, updated_at: string): ChatThread => ({
  id, client_id: 1, year_start: '2026-04-01', title: id, created_at: updated_at, updated_at,
})

const question = (kind: Question['kind']): Question => ({
  id: 'q1', client_id: 1, year_start: '2026-04-01', row_ids: [4], kind, text: 'When was this taxi?',
  why: '£18.00, no date on it and no matching bank line.', source: 'rules', status: 'open', answer: null,
  created_at: '2026-11-02T10:00:00+00:00', resolved_at: null,
})

const decision = (rule: string): Decision => ({
  id: 'd1', client_id: 1, thread_id: 't1', year_start: '2026-04-01', action: 'keep_one', rule, status: 'applied',
  row_ids: [1, 2], evidence: [], reason: '', before: {}, after: {}, actor: 'agent:m', reverses: null,
  created_at: '2026-11-02T10:00:00+00:00', prev_hash: '', hash: 'h',
})

const resultJson = '{"sorted":[],"questions":[],"trial_balance":null,"post":null}'
const answerJson = JSON.stringify({ question: question('date'), sorted: [], trial_balance: null, post: null })

test('an event split across two chunks arrives once, whole', () => {
  const first = parseEvents('event: step\ndata: {"id":"f1","text":"Read', '')
  assert.deepEqual(first.events, [])
  const second = parseEvents(' a.csv","state":"done"}\n\nevent: token\ndata: {"text":"Hi"}\n\n', first.carry)
  assert.deepEqual(second.events, [
    { type: 'step', data: { id: 'f1', text: 'Read a.csv', state: 'done' } },
    { type: 'token', data: { text: 'Hi' } },
  ])
  assert.equal(second.carry, '')
})

test('events separated by CRLF, with comments and several data lines, parse', () => {
  const { events, carry } = parseEvents(
    ': keep-alive\r\n\r\nevent: result\r\ndata: ' + resultJson + '\r\n\r\nevent: done\r\ndata: {}\r\n\r\nevent: tok', '')
  assert.deepEqual(events.map(e => e.type), ['result', 'done'])
  assert.equal(carry, 'event: tok')
  const joined = parseEvents('event: token\ndata: {"text":\ndata: "two lines"}\n\n', '')
  assert.deepEqual(joined.events, [{ type: 'token', data: { text: 'two lines' } }])
})

test('an event the client does not know is skipped', () => {
  assert.deepEqual(parseEvents('event: ping\ndata: {}\n\n', '').events, [])
})

test('threads group by the calendar day, across midnight', () => {
  const now = new Date(2026, 10, 2, 0, 5)   // 00:05 on 2 Nov, local time
  const groups = groupThreads([
    thread('earlier', new Date(2026, 9, 31, 23, 59).toISOString()),
    thread('yesterday-late', new Date(2026, 10, 1, 23, 59).toISOString()),
    thread('today', new Date(2026, 10, 2, 0, 1).toISOString()),
    thread('yesterday-early', new Date(2026, 10, 1, 0, 0).toISOString()),
  ], now)
  assert.deepEqual(groups.map(g => [g.label, g.threads.map(t => t.id)]), [
    ['Today', ['today']],
    ['Yesterday', ['yesterday-late', 'yesterday-early']],
    ['Earlier', ['earlier']],
  ])
})

test('empty groups are left out', () => {
  const now = new Date(2026, 10, 2, 12, 0)
  assert.deepEqual(groupThreads([thread('a', new Date(2026, 10, 2, 9).toISOString())], now).map(g => g.label), ['Today'])
  assert.deepEqual(groupThreads([], now), [])
})

test('each kind of question gets its control', () => {
  assert.equal(questionControl(question('date')), 'date')
  assert.equal(questionControl(question('receipt_or_invoice')), 'upload')
  assert.equal(questionControl(question('vat_invoice')), 'upload')
  assert.equal(questionControl(question('payout_report')), 'upload')
  assert.equal(questionControl(question('payroll_report')), 'upload')
  assert.equal(questionControl(question('other')), 'text')
  assert.equal(questionControl(question('opening_prepayments')), 'split')
  assert.equal(questionControl(question('opening_accruals')), 'split')
  assert.equal(questionControl(question('bad_debt')), 'write_off')
})

test('an opening balance question says how much is to be split, and the lines are added up in pence', () => {
  const q = { ...question('opening_prepayments'), text: 'Opening prepayments of £6,558.46: which costs are they for?' }
  assert.equal(openingAmount(q), '6558.46')
  assert.equal(openingAmount(question('date')), null)
  const vat = { ...question('opening_vat'), text: 'The VAT payment of £27,412.00 on 13 Apr 2023 is £312.00 more than the £27,100.00 owed when the year began: what was the difference for?' }
  assert.equal(openingAmount(vat), '312.00')
  assert.equal(questionControl(vat), 'split')
  assert.equal(splitTotal([{ amount: '1020' }, { amount: '5538.46' }]), '6558.46')
  assert.equal(splitTotal([{ amount: '0.1' }, { amount: '0.2' }]), '0.30')   // no floating point pence
  assert.equal(splitTotal([{ amount: '' }, { amount: 'abc' }]), '0.00')
})

test('the rule badge is the rule number', () => {
  assert.equal(ruleBadge(decision('R2 Duplicate: kept the receipt')), 'R2')
  assert.equal(ruleBadge(decision('R1 Date from the bank')), 'R1')
  assert.equal(ruleBadge(decision('Documentation required')), '')
})

test('money shows pounds with thousands and two decimals', () => {
  assert.equal(formatMoney('1412.68'), '£1,412.68')
  assert.equal(formatMoney('1234567.5'), '£1,234,567.50')
  assert.equal(formatMoney('-1412.68'), '-£1,412.68')
  assert.equal(formatMoney('0'), '£0.00')
  assert.equal(formatMoney('240.00'), '£240.00')
  assert.equal(formatMoney('-0.00'), '£0.00')
})

test('a Suspense item says what it needs', () => {
  assert.equal(suspenseLabel('receipt_or_invoice'), 'needs receipt or invoice')
  assert.equal(suspenseLabel('vat_invoice'), 'needs VAT invoice')
  assert.equal(suspenseLabel(null), 'Suspense')   // no longer held
})

test('statements are told apart by their name', () => {
  assert.equal(looksLikeStatement('barclays-oct.csv'), true)
  assert.equal(looksLikeStatement('Statement October.pdf'), true)
  assert.equal(looksLikeStatement('export.OFX'), true)
  assert.equal(looksLikeStatement('costco-receipt.jpg'), false)
  assert.equal(looksLikeStatement('invoice-240.pdf'), false)
})

test('the posted table shows five accounts and Suspense, skipping empty ones', () => {
  const line = (code: string, debit = '10.00', credit = '0.00') => ({ code, name: code, type: 'expense', debit, credit })
  const tb = {
    lines: [line('1200', '0.00', '1412.68'), line('4000', '0.00', '0.00'), line('7400'), line('7500'), line('7600'),
            line('7700'), line('7800'), line('9998', '240.00')],
  } as unknown as PostedTrialBalance
  const { shown, more } = shownAccounts(tb)
  assert.deepEqual(shown.map(l => l.code), ['1200', '7400', '7500', '7600', '7700', '9998'])
  assert.equal(more, 1)
})

const sse = (text: string, chunks = 3) => {
  const size = Math.ceil(text.length / chunks)
  const parts = Array.from({ length: chunks }, (_, i) => text.slice(i * size, (i + 1) * size))
  return new Response(new ReadableStream({
    start(c) { for (const p of parts) c.enqueue(new TextEncoder().encode(p)); c.close() },
  }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

test('a message is sent with its files and bank accounts, and its events streamed back', async () => {
  let url = ''
  let sent: RequestInit | undefined
  globalThis.fetch = (async (u: string, init?: RequestInit) => {
    url = u
    sent = init
    return sse('event: status\ndata: {"text":"Working on it…"}\n\nevent: token\ndata: {"text":"Done."}\n\n' +
               'event: done\ndata: {}\n\n', 4)
  }) as typeof fetch
  const events: ChatEvent[] = []
  const files = [new File(['a'], 'bank.csv'), new File(['b'], 'receipt.jpg')]
  await streamMessage('t1', 'Review these', files, ['1201', ''], e => events.push(e), new AbortController().signal)
  assert.equal(url, '/api/chat/threads/t1/messages')
  assert.equal(new Headers(sent?.headers).get('X-LedgerSync'), '1')
  const body = sent?.body as FormData
  assert.equal(body.get('text'), 'Review these')
  assert.deepEqual((body.getAll('files') as File[]).map(f => f.name), ['bank.csv', 'receipt.jpg'])
  assert.deepEqual(body.getAll('bank_accounts'), ['1201', ''])
  assert.deepEqual(events.map(e => e.type), ['status', 'token', 'done'])
})

test('a second message while the first runs is refused with the reason', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: 'Still working on the last message.' }),
    { status: 409, headers: { 'Content-Type': 'application/json' } })) as typeof fetch
  await assert.rejects(streamMessage('t1', 'again', [], [], () => {}, new AbortController().signal),
    (e: unknown) => e instanceof ApiError && e.code === 'http_409' && e.message === 'Still working on the last message.')
})

test('an answer is posted as JSON with the header and returns that question and its effect', async () => {
  let sent: { url: string; init?: RequestInit } | undefined
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    sent = { url, init }
    return new Response(answerJson, { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  const answered = await answerQuestion('t1', 'q1', { kind: 'date', date: '2026-10-03' })
  assert.equal(sent?.url, '/api/chat/threads/t1/questions/q1/answer')
  assert.equal(sent?.init?.method, 'POST')
  assert.equal(new Headers(sent?.init?.headers).get('X-LedgerSync'), '1')
  assert.deepEqual(JSON.parse(String(sent?.init?.body)), { kind: 'date', date: '2026-10-03' })
  assert.equal(answered.question.id, 'q1')
})

test('a document for a question is uploaded as its file', async () => {
  let sent: { url: string; init?: RequestInit } | undefined
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    sent = { url, init }
    return new Response(answerJson, { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  await uploadForQuestion('t1', 'q2', new File(['%PDF'], 'invoice.pdf'))
  assert.equal(sent?.url, '/api/chat/threads/t1/questions/q2/document')
  assert.equal(new Headers(sent?.init?.headers).get('X-LedgerSync'), '1')
  assert.equal(((sent?.init?.body as FormData).get('file') as File).name, 'invoice.pdf')
})

test('a decision shows each changed field of each row, before and after, in words', () => {
  const d = {
    ...decision('R4 Conflict: used the invoice'),
    before: { '7': { gross: '27.50', date: null, excluded: false } },
    after: { '7': { gross: '30.22', date: '2026-10-14', excluded: true }, '8': { vat: '5.04' } },
  }
  assert.deepEqual(changedFields(d), [
    { row: 7, field: 'Amount', before: '£27.50', after: '£30.22' },
    { row: 7, field: 'Date', before: '—', after: '14 Oct 2026' },
    { row: 7, field: 'Removed from the books', before: 'No', after: 'Yes' },
    { row: 8, field: 'VAT', before: '—', after: '£5.04' },
  ])
})

test("a file's chip follows the steps that name it", () => {
  const steps = [
    { id: 'a', text: 'Read a.csv (12 rows)', state: 'done' as const, file: 'a.csv', rows: 12 },
    { id: 'b', text: 'Reading b.jpg…', state: 'running' as const, file: 'b.jpg' },
    { id: 'c', text: "Couldn't read c.pdf: it has no text", state: 'failed' as const, file: 'c.pdf', reason: 'it has no text' },
    { id: 'd', text: 'Read d.csv (1 row)', state: 'done' as const, file: 'd.csv', rows: 1 },
  ]
  assert.deepEqual(fileStatus('a.csv', steps), { state: 'done', label: 'Read (12 rows)' })
  assert.deepEqual(fileStatus('d.csv', steps), { state: 'done', label: 'Read (1 row)' })
  assert.deepEqual(fileStatus('b.jpg', steps), { state: 'reading', label: 'Reading' })
  assert.deepEqual(fileStatus('c.pdf', steps), { state: 'failed', label: 'Failed: it has no text' })
  assert.deepEqual(fileStatus('e.png', steps), { state: 'queued', label: 'Queued' })
})

test('a retry sends again only the files that were not read', () => {
  const files = [new File(['a'], 'a.csv'), new File(['c'], 'c.pdf'), new File(['e'], 'e.png')]
  const steps = [
    { id: 'a', text: 'Read a.csv', state: 'done' as const, file: 'a.csv', rows: 2 },
    { id: 'c', text: "Couldn't read c.pdf", state: 'failed' as const, file: 'c.pdf' },
  ]
  assert.deepEqual(retryFiles(files, ['1200', '', ''], steps).files.map(f => f.name), ['c.pdf', 'e.png'])
  assert.deepEqual(retryFiles(files, ['1200', '1201', ''], steps).bankAccounts, ['1201', ''])
})

test('withQuestion updates every card for the question', () => {
  const card = question('date'), answered = { ...card, status: 'resolved' as const, answer: '9 Oct 2026' }
  const result = { sorted: [], questions: [card], trial_balance: null, post: null }
  const items = [{ result }, { result: null }, { result: { ...result } }]
  const next = withQuestion(items, answered)
  assert.deepEqual([next[0].result?.questions[0].status, next[1].result, next[2].result?.questions[0].answer],
                   ['resolved', null, '9 Oct 2026'])
})

test('a question says where it stands', () => {
  assert.equal(questionState(question('date')), null)
  assert.equal(questionState({ ...question('date'), status: 'resolved', answer: '9 Oct 2026' }), 'Answered: 9 Oct 2026')
  assert.equal(questionState({ ...question('receipt_or_invoice'), status: 'resolved', answer: null }), 'Resolved')
  assert.equal(questionState({ ...question('receipt_or_invoice'), status: 'waiting', answer: "I don't have it" }),
               'Waiting for the receipt or invoice')
  assert.equal(questionState({ ...question('vat_invoice'), status: 'waiting', answer: "I don't have it" }),
               'Waiting for the VAT invoice')
  assert.equal(questionState({ ...question('date'), status: 'waiting', answer: 'Not sure' }), 'Waiting: not sure of the date yet')
})

test("an answer's effect is one line", () => {
  const tb = (n: number) => ({ is_balanced: true, suspense: Array(n).fill({}) }) as unknown as PostedTrialBalance
  const a = (over: Partial<AnswerResult>): AnswerResult => ({ question: question('date'), sorted: [], trial_balance: null, post: null, ...over })
  assert.equal(effectLine(a({})), null)
  assert.equal(effectLine(a({ trial_balance: tb(0) })), 'Posted · balanced · nothing in Suspense')
  assert.equal(effectLine(a({ trial_balance: tb(1) })), 'Posted · balanced · 1 item in Suspense')
  assert.equal(effectLine(a({ post: { problems: ['Row 3 has no date.'] } as PostResult })), 'Nothing was posted: Row 3 has no date.')
  const leftOut = { problems: [], left_out: ['Tallgrass (15 May 2023): read as USD.'] } as unknown as PostResult
  assert.equal(effectLine(a({ trial_balance: tb(0), post: leftOut })),
               'Posted · balanced · nothing in Suspense · 1 row left out until it is fixed')
})

test('hasResult and readStatus', () => {
  assert.equal(hasResult({ sorted: [], questions: [], trial_balance: null, post: null }), false)
  assert.equal(hasResult({ sorted: [decision('R1')], questions: [], trial_balance: null, post: null }), true)
  assert.deepEqual(readStatus({ name: 'a.csv', state: 'done', rows: 9, reason: null }), { state: 'done', label: 'Read (9 rows)' })
  assert.deepEqual(readStatus({ name: 'b.png', state: 'failed', rows: null, reason: 'Unreadable.' }), { state: 'failed', label: 'Failed: Unreadable.' })
})

test('the Overview link starts a chat that asks what needs attention', () => {
  assert.equal(attentionHref(7), '/chat?client=7&ask=What%20needs%20my%20attention%3F')
  assert.equal(attentionHref(7, '2020-11-02'), '/chat?client=7&year=2020-11-02&ask=What%20needs%20my%20attention%3F')
  // The questions waiting are answered on the year's AI review list, with no chat (and no model) needed.
  assert.equal(questionsHref(7, '2023-04-01'), '/clients/7/2023-04-01/ai-review')
})

test('a chat is polled only while a turn runs that this page did not send', () => {
  assert.equal(shouldPoll({ running: true }, false), true)
  assert.equal(shouldPoll({ running: true }, true), false)
  assert.equal(shouldPoll({ running: false }, false), false)
})

test('agentDecisions leaves out a person\'s decisions, and says when none are loaded', () => {
  const made = (id: string, actor: string) => ({ id, actor }) as Decision
  const loaded = new Map([['a', made('a', 'agent:qwen')], ['u', made('u', 'user')], ['r', made('r', 'rules')]])
  assert.deepEqual(agentDecisions(['a', 'u', 'r'], loaded)?.map(d => d.id), ['a', 'r'])
  assert.deepEqual(agentDecisions(['u'], loaded), [])
  assert.equal(agentDecisions(['x'], loaded), null)
})

test('a purchase waiting for its receipt or invoice can be booked without it; a report cannot', () => {
  assert.equal(canBookWithout(question('receipt_or_invoice')), true)
  assert.equal(canBookWithout(question('vat_invoice')), true)
  assert.equal(canBookWithout(question('payout_report')), false)
  assert.equal(canBookWithout(question('date')), false)
  assert.equal(questionState({ ...question('receipt_or_invoice'), status: 'resolved',
                               answer: 'Booked without a receipt: Lost' }), 'Booked without a receipt: Lost')
})

test('the marks a model puts round a phrase are dropped from its reply, the words kept', async () => {
  const { plainReply } = await import('./chat.ts')
  assert.equal(plainReply('1. **7400 Travel**: the usual home for a toll.\n## Options\nUse `7400`. 2 * 3 * 4 stays.'),
               '1. 7400 Travel: the usual home for a toll.\nOptions\nUse 7400. 2 * 3 * 4 stays.')
})

test('a chat\'s title is the thread list\'s once that has it, as the first message titles the chat', async () => {
  const { currentTitle } = await import('./chat.ts')
  const opened = { ...thread('t1', '2026-11-15T10:00:00+00:00'), title: 'New chat' }
  assert.equal(currentTitle(opened, null), 'New chat')                       // the list hasn't arrived
  assert.equal(currentTitle(opened, [thread('t2', '2026-11-15T10:00:00+00:00')]), 'New chat')   // not in it yet
  const titled = { ...opened, title: 'What needs my attention?' }
  assert.equal(currentTitle(opened, [thread('t2', '2026-11-15T10:00:00+00:00'), titled]), 'What needs my attention?')
})

test('a chat is deleted with the header, and the API\'s empty answer is not read as JSON', async () => {
  let sent: { url: string; init?: RequestInit } | undefined
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    sent = { url, init }
    return new Response(null, { status: 204 })
  }) as typeof fetch
  assert.equal(await deleteThread('t1'), undefined)
  assert.equal(sent?.url, '/api/chat/threads/t1')
  assert.equal(sent?.init?.method, 'DELETE')
  assert.equal(new Headers(sent?.init?.headers).get('X-LedgerSync'), '1')
})

test('a chat with a message still running is not deleted, and the reason comes back', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: 'Still working on the last message.' }),
    { status: 409, headers: { 'Content-Type': 'application/json' } })) as typeof fetch
  await assert.rejects(deleteThread('t1'),
    (e: unknown) => e instanceof ApiError && e.code === 'http_409' && e.message === 'Still working on the last message.')
})

test('deleting a chat asks by its title and client, and says the books are kept', async () => {
  const t = { ...thread('t1', '2026-11-15T10:00:00+00:00'), title: 'October review' }
  const asked = deleteQuestion(t, 'Northbridge Ltd')
  assert.match(asked, /^Delete the chat "October review" for Northbridge Ltd\?/)
  assert.match(asked, /books keep/)
  assert.match(asked, /cannot be undone/)
  assert.match(deleteQuestion(t, ''), /^Delete the chat "October review"\?/)     // the clients haven't arrived
})

test('deleting the open chat leads to a new chat; deleting another leaves the page where it is', async () => {
  assert.equal(afterDelete('t1', 't1'), '/chat')
  assert.equal(afterDelete('t1', 't2'), null)
  assert.equal(afterDelete('t1', undefined), null)                            // on New chat already
})

test('a chat is renamed with the header, and the renamed chat comes back', async () => {
  let sent: { url: string; init?: RequestInit } | undefined
  const renamed = { ...thread('t1', '2026-11-15T10:00:00+00:00'), title: 'October review' }
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    sent = { url, init }
    return new Response(JSON.stringify(renamed), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  assert.deepEqual(await renameThread('t1', 'October review'), renamed)
  assert.equal(sent?.url, '/api/chat/threads/t1')
  assert.equal(sent?.init?.method, 'PATCH')
  assert.equal(new Headers(sent?.init?.headers).get('X-LedgerSync'), '1')
  assert.deepEqual(JSON.parse(String(sent?.init?.body)), { title: 'October review' })
})

test('a typed title is trimmed and kept to the API\'s length; an empty or unchanged one renames nothing', async () => {
  assert.equal(newTitle('  October review ', 'New chat'), 'October review')
  assert.equal(newTitle('   ', 'New chat'), null)
  assert.equal(newTitle(' New chat ', 'New chat'), null)
  assert.equal(newTitle('x'.repeat(80), 'New chat'), 'x'.repeat(60))
})

test('waiting questions are counted by year: the one on show, and each other year with some', () => {
  // mind Limited: 22 waited in the year to 1 Nov 2021, and the overview of the year to 1 Nov 2027 counted them as its own.
  const years = [{ start: '2020-11-02', end: '2021-11-01', label: 'Year to 1 Nov 2021', closed: false },
                 { start: '2026-11-02', end: '2027-11-01', label: 'Year to 1 Nov 2027', closed: false }]
  const q = (year_start: string, status: Question['status']) => ({ ...question('date'), year_start, status })
  const asked = [q('2020-11-02', 'open'), q('2020-11-02', 'waiting'), q('2020-11-02', 'resolved'), q('2026-11-02', 'open')]
  assert.deepEqual(waitingByYear(asked, years, '2026-11-02'),
                   { here: 1, elsewhere: [{ start: '2020-11-02', label: 'Year to 1 Nov 2021', count: 2 }] })
  assert.deepEqual(waitingByYear([], years, '2026-11-02'), { here: 0, elsewhere: [] })
})

// ─── An answer the agent filled in, to change or confirm (design of 2026-11-25) ────────────────────────────────

import { changedLines, fromQuestion, nextLines, offerDate, offerLines, sourcesFor, type Offer } from './chat.ts'

const offer = (answer: Offer['answer']): Offer => ({
  answer,
  sources: [
    { kind: 'said', quote: 'the rent and the insurance' },
    { kind: 'document', upload_id: 4, upload_name: 'he-2403.pdf', quote: 'Rent, quarter 25 Mar to 23 Jun', for: 'line:1',
      working: '£6,000.00 for 91 days, 84 of them in this year' },
    { kind: 'question' },
  ],
  reason: 'The client said they were the rent and the insurance.',
  thread_id: 't1', offered_at: '2026-11-25T12:00:00+00:00', offered_by: 'agent:test',
})
const offered = (answer: Offer['answer']): Question => ({ ...question('opening_prepayments'), offer: offer(answer) })
const SPLIT = { kind: 'split' as const, lines: [{ account: '7100', amount: '5538.46' }, { account: '8204', amount: '1020.00' }] }

test('an offered split fills in the form, and a question without one leaves it empty', () => {
  assert.deepEqual(offerLines(offered(SPLIT)), [{ account: '7100', amount: '5538.46' }, { account: '8204', amount: '1020.00' }])
  assert.equal(offerLines(question('opening_prepayments')), null)
  assert.equal(offerDate(offered({ kind: 'write_off', date: '2024-01-31' })), '2024-01-31')
  assert.equal(offerDate(offered({ kind: 'write_off' })), null)   // left to the default: when the six months end
})

test('a line shows its own document quote and what the question itself gave', () => {
  const q = offered(SPLIT)
  assert.deepEqual(sourcesFor(q, 'line:1').map(s => s.kind), ['document', 'question'])
  assert.deepEqual(sourcesFor(q, 'line:2').map(s => s.kind), ['question'])
  assert.deepEqual(sourcesFor(question('opening_prepayments'), 'line:1'), [])
})

test('only the line the person edited is marked as changed by them', () => {
  const was = offerLines(offered(SPLIT))!
  assert.deepEqual(changedLines(was, [was[0], { account: '8204', amount: '1000.00' }]), [false, true])
  assert.deepEqual(changedLines(was, [...was, { account: '7200', amount: '20.00' }]), [false, false, true])   // added
})

test('an offer that arrives later fills the form unless the person has started on it', () => {
  const blank = [{ account: '', amount: '' }]
  assert.deepEqual(nextLines(blank, offered(SPLIT), false), offerLines(offered(SPLIT)))
  const typed = [{ account: '7100', amount: '10.00' }]
  assert.deepEqual(nextLines(typed, offered(SPLIT), true), typed)                    // theirs stays
  assert.deepEqual(nextLines(blank, question('opening_prepayments'), false), blank)  // nothing offered
})

test("a one-line answer shows its figure is the question's own amount", () => {
  const whole = offered({ kind: 'split', lines: [{ account: '8250', amount: '312.00' }] })
  assert.equal(fromQuestion(whole, 1), true)
  assert.equal(fromQuestion(offered(SPLIT), 1), false)   // two lines: the question's amount backs neither alone
  assert.equal(fromQuestion(question('opening_vat'), 1), false)
})
