// Run with: npm test.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { activityLines, aiChanges, isReversed, lastReviewed, newestFirst, overviewReviewLine, reviewNotice, runTitle, unseenChanges,
         type ReviewDetail } from './reviews.ts'
import type { Decision, Question } from './chat.ts'

const decision = (id: string, status: Decision['status']): Decision => ({
  id, client_id: 1, thread_id: null, year_start: '2026-04-01', action: 'keep_one', rule: 'R2', status, trigger: 'background',
  row_ids: [1], evidence: [], reason: '', before: {}, after: {}, actor: 'agent:m', reverses: null,
  created_at: '2026-11-04T10:42:00', prev_hash: '', hash: 'h',
})
const question = (id: string): Question => ({
  id, client_id: 1, year_start: '2026-04-01', row_ids: [4], kind: 'date', text: 'When?', why: 'why', source: 'agent',
  status: 'open', answer: null, created_at: '2026-11-04T10:42:00', resolved_at: null,
})
const run = (over: Partial<ReviewDetail> = {}): ReviewDetail => ({
  id: 'r1', client_id: 1, year_start: '2026-04-01', status: 'done', started_at: '2026-11-04T10:42:00', finished_at: null,
  trigger_summary: 'after 3 files were added', from_seq: 1, to_seq: 3, decision_ids: [], question_ids: [], looked_at: [],
  summary: '', error: '', seen: false, decisions: [], questions: [], applied: {}, ...over,
})
const now = new Date(2026, 10, 4, 15, 0)   // Wed 4 Nov 2026

test('runTitle: today, with sorted and asked parts', () => {
  const r = run({ decisions: [decision('a', 'applied'), decision('b', 'applied')], questions: [question('q')] })
  assert.equal(runTitle(r, now), 'Today 10:42, after 3 files were added: sorted 2, asked 1')
})

test('runTitle: omits zero parts', () => {
  assert.equal(runTitle(run({ decisions: [decision('a', 'applied')] }), now), 'Today 10:42, after 3 files were added: sorted 1')
  assert.equal(runTitle(run({ questions: [question('q')] }), now), 'Today 10:42, after 3 files were added: asked 1')
})

test('runTitle: nothing to change', () => {
  assert.equal(runTitle(run(), now), 'Today 10:42, after 3 files were added: Nothing to change.')
})

test('a review still running does not say there is nothing to change', () => {
  const running = run({ status: 'running' })
  assert.equal(runTitle(running, now), 'Today 10:42, after 3 files were added')
})

test('runTitle: suggest mode says suggested', () => {
  const r = run({ decisions: [decision('a', 'suggested'), decision('b', 'suggested')] })
  assert.equal(runTitle(r, now), 'Today 10:42, after 3 files were added: suggested 2')
})

test('runTitle: yesterday and older days', () => {
  assert.equal(runTitle(run({ started_at: '2026-11-03T09:05:00' }), now), 'Yesterday 09:05, after 3 files were added: Nothing to change.')
  assert.equal(runTitle(run({ started_at: '2026-11-03T09:05:00', decisions: [decision('a', 'applied')] }), new Date(2026, 10, 5, 8, 0)),
    'Tue 3 Nov 09:05, after 3 files were added: sorted 1')
})

test('overviewReviewLine', () => {
  assert.equal(overviewReviewLine(null, 3), null)
  assert.equal(overviewReviewLine('2026-11-04T10:42:00', 0), "AI review: last run 10:42. 0 changes you haven't looked at")
  assert.equal(overviewReviewLine('2026-11-04T10:42:00', 1), "AI review: last run 10:42. 1 change you haven't looked at")
  assert.equal(overviewReviewLine('2026-11-04T10:42:00', 2), "AI review: last run 10:42. 2 changes you haven't looked at")
})

test('unseenChanges counts applied and suggested changes of unseen done runs, not undos, seen or other runs', () => {
  const undo = { ...decision('u', 'applied'), reverses: 'a' }
  const runs = [
    run({ decisions: [decision('a', 'applied'), undo, decision('s', 'suggested')] }),
    run({ id: 'r2', seen: true, decisions: [decision('b', 'applied')] }),
    run({ id: 'r3', status: 'failed', decisions: [decision('c', 'applied'), decision('d', 'applied')] }),
  ]
  assert.equal(unseenChanges(runs), 2)
  assert.equal(isReversed(runs[0], 'a'), true)
  assert.equal(isReversed(runs[0], 'x'), false)
})

test('newestFirst orders by start', () => {
  const order = newestFirst([run({ id: 'old', started_at: '2026-11-01T10:00:00' }), run({ id: 'new', started_at: '2026-11-04T10:00:00' })])
  assert.deepEqual(order.map(r => r.id), ['new', 'old'])
})

// The notice and the history of the AI review page. Runs are given newest first, as the page holds them.
const later = new Date(2026, 10, 15, 12, 0)   // Sun 15 Nov 2026
const failed = (id: string, time: string, error = 'API key expired', more: Partial<ReviewDetail> = {}) =>
  run({ id, status: 'failed', started_at: `2026-11-13T${time}:00`, error, ...more })
const five = [failed('f5', '17:13'), failed('f4', '17:03'), failed('f3', '16:53'), failed('f2', '16:43'), failed('f1', '16:33')]
const done = (id: string, time: string, more: Partial<ReviewDetail> = {}) =>
  run({ id, status: 'done', started_at: `2026-11-13T${time}:00`, ...more })

test('five failures at the top are one notice with Try again', () => {
  assert.deepEqual(reviewNotice([...five, done('d', '12:00')], later), {
    kind: 'failed', retry: true, text: "The review hasn't finished since Fri 13 Nov 16:33: API key expired (5 tries).",
  })
})

test('one failure says 1 try; no error leaves the colon out', () => {
  assert.equal(reviewNotice([failed('f1', '16:33')], later)?.text, "The review hasn't finished since Fri 13 Nov 16:33: API key expired (1 try).")
  assert.equal(reviewNotice([failed('f1', '16:33', '')], later)?.text, "The review hasn't finished since Fri 13 Nov 16:33 (1 try).")
})

test('a run still going after failures says Reviewing…', () => {
  assert.deepEqual(reviewNotice([run({ id: 'g', status: 'running' }), ...five], later), { kind: 'reviewing', retry: false, text: 'Reviewing…' })
})

test('a success at the top, or no runs, has no notice', () => {
  assert.equal(reviewNotice([done('d', '18:00'), ...five], later), null)
  assert.equal(reviewNotice([], later), null)
})

test('paused and off are notices without a button', () => {
  assert.deepEqual(reviewNotice([run({ status: 'limited' }), ...five], later),
                   { kind: 'limited', retry: false, text: 'AI review is paused for today: limit reached.' })
  assert.deepEqual(reviewNotice([run({ status: 'off' })], later), { kind: 'off', retry: false, text: 'AI review is off for this client.' })
})

test('failures with different errors: the notice counts all of them and gives the newest error', () => {
  const runs = [failed('f3', '16:53', 'Timed out'), failed('f2', '16:43'), failed('f1', '16:33'), done('d', '12:00'), failed('f0', '11:00')]
  assert.equal(reviewNotice(runs, later)?.text, "The review hasn't finished since Fri 13 Nov 16:33: Timed out (3 tries).")
})

test('five failures with one error fold into one activity line', () => {
  assert.deepEqual(activityLines(five, later), [
    { key: 'f5', failed: true, text: "Fri 13 Nov 16:33 to 17:13 · 5 runs didn't finish: API key expired" },
  ])
})

test('a fold over midnight says both days', () => {
  const runs = [run({ id: 'f2', status: 'failed', started_at: '2026-11-14T00:05:00', error: 'x' }), failed('f1', '23:55', 'x')]
  assert.equal(activityLines(runs, later)[0].text, "Fri 13 Nov 23:55 to Yesterday 00:05 · 2 runs didn't finish: x")
})

test('a success between failures breaks the fold', () => {
  const lines = activityLines([failed('f2', '17:00'), done('d', '16:45'), failed('f1', '16:33')], later)
  assert.deepEqual(lines.map(l => [l.key, l.failed]), [['f2', true], ['d', false], ['f1', true]])
  assert.equal(lines[0].text, "Fri 13 Nov 17:00, after 3 files were added · didn't finish: API key expired")
})

test('failures with different errors are separate lines', () => {
  const lines = activityLines([failed('f3', '16:53', 'Timed out'), failed('f2', '16:43'), failed('f1', '16:33')], later)
  assert.deepEqual(lines.map(l => l.text), [
    "Fri 13 Nov 16:53, after 3 files were added · didn't finish: Timed out",
    "Fri 13 Nov 16:33 to 16:43 · 2 runs didn't finish: API key expired",
  ])
})

test('a failure with no error or trigger says only that it did not finish', () => {
  assert.equal(activityLines([failed('f1', '16:33', '', { trigger_summary: '' })], later)[0].text, "Fri 13 Nov 16:33 · didn't finish")
})

test('a finished run reads as its title, with what the checks stopped', () => {
  const r = done('d', '12:00', { decisions: [decision('a', 'applied'), decision('b', 'refused'), decision('c', 'refused')] })
  assert.deepEqual(activityLines([r], later), [{
    key: 'd', failed: false,
    text: 'Fri 13 Nov 12:00, after 3 files were added: sorted 1. 2 other changes the AI tried were stopped by the checks and not made.',
  }])
  assert.equal(activityLines([done('d', '12:00')], later)[0].text, 'Fri 13 Nov 12:00, after 3 files were added: Nothing to change.')
})

test('paused and off runs are their own activity lines', () => {
  const lines = activityLines([run({ id: 'l', status: 'limited', started_at: '2026-11-13T09:00:00' }),
                               run({ id: 'o', status: 'off', started_at: '2026-11-13T08:00:00' })], later)
  assert.deepEqual(lines.map(l => l.text), ['Fri 13 Nov 09:00: paused for today: limit reached', 'Fri 13 Nov 08:00: AI review is off for this client'])
})

test('aiChanges lists applied changes newest first and leaves out undos, undone and refused', () => {
  const undo = { ...decision('u', 'applied'), reverses: 'c' }
  const runs = [
    done('new', '17:00', { decisions: [decision('a', 'applied'), decision('b', 'refused'), decision('s', 'suggested')] }),
    done('old', '12:00', { decisions: [decision('c', 'applied'), undo, decision('d', 'applied'), decision('e', 'applied')] }),
    failed('f', '11:00', 'x', { decisions: [decision('z', 'applied')] }),
  ]
  assert.deepEqual(aiChanges(runs, new Set(['d']), new Set()).map(c => c.decision.id), ['a', 'e'])
})

test('aiChanges marks the changes of runs not yet seen', () => {
  const runs = [done('new', '17:00', { decisions: [decision('a', 'applied')] }), done('old', '12:00', { decisions: [decision('e', 'applied')] })]
  assert.deepEqual(aiChanges(runs, new Set(), new Set(['new'])).map(c => [c.decision.id, c.fresh]), [['a', true], ['e', false]])
})

test('lastReviewed is the newest finished run, null when none finished', () => {
  assert.equal(lastReviewed([...five, done('d', '12:00'), done('e', '09:00')], later), 'Fri 13 Nov 12:00')
  assert.equal(lastReviewed(five, later), null)
})
