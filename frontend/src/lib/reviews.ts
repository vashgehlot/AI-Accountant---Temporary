// The background AI review (design of 2026-11-04): the runs a client's books had after a change, what they did and
// asked, and the calls that list them, undo or apply a change and answer their questions. Paths go through the Next
// rewrite like every other call. The pure functions are tested in reviews.test.ts.
import { request } from './api.ts'
import type { Answer, AnswerResult, Decision, Question } from './chat.ts'

export type ReviewStatus = 'running' | 'done' | 'failed' | 'limited' | 'off'

export interface ReviewRun {
  id: string
  client_id: number
  year_start: string
  status: ReviewStatus
  started_at: string
  finished_at: string | null
  trigger_summary: string    // "after 3 files were added"
  from_seq: number
  to_seq: number
  decision_ids: string[]
  question_ids: string[]
  looked_at: number[]
  issues_seen?: string[]    // the issues it was shown, as "row:code:digest" keys
  summary: string
  error: string
  seen: boolean
}

export interface ReviewDetail extends ReviewRun {
  decisions: Decision[]
  questions: Question[]
  applied: Record<string, string>   // a suggestion's id -> the decision that applied it
}

const WRITE = { 'X-LedgerSync': '1' }
const post = (path: string) => request<unknown>(path, { method: 'POST', headers: WRITE })

export const listReviews = (clientId: number, yearStart: string) =>
  request<ReviewDetail[]>(`/api/clients/${clientId}/reviews?year_start=${encodeURIComponent(yearStart)}`)
// The year's suggestions a person can still apply: the review's, and the account changes the rules suggest.
export const listSuggestions = (clientId: number, yearStart: string) =>
  request<Decision[]>(`/api/clients/${clientId}/years/${yearStart}/suggestions`)
export const markReviewsSeen = (clientId: number) => post(`/api/clients/${clientId}/reviews/seen`)
// Try again: the client's review is due now. One already running is left to finish.
export const retryReview = (clientId: number) => post(`/api/clients/${clientId}/reviews/retry`)
export const undoDecision =(clientId: number, id: string) =>
  request<Decision>(`/api/clients/${clientId}/decisions/${id}/undo`, { method: 'POST', headers: WRITE })
export const applySuggestion = (clientId: number, id: string) =>
  request<Decision>(`/api/clients/${clientId}/decisions/${id}/apply`, { method: 'POST', headers: WRITE })

// How a QuestionCard answers: through the client's own routes, with no chat.
export interface Answerer {
  answer: (questionId: string, a: Answer) => Promise<AnswerResult>
  upload: (questionId: string, file: File) => Promise<AnswerResult>
}

export const clientAnswerer = (clientId: number): Answerer => ({
  answer: (qid, a) => request<AnswerResult>(`/api/clients/${clientId}/questions/${qid}/answer`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...WRITE }, body: JSON.stringify(a),
  }, 120_000),
  upload: (qid, file) => {
    const data = new FormData()
    data.append('file', file)
    return request<AnswerResult>(`/api/clients/${clientId}/questions/${qid}/document`,
                                 { method: 'POST', body: data, headers: WRITE }, 180_000)
  },
})

const pad = (n: number) => String(n).padStart(2, '0')
const clock = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate())

// "Today 10:42", "Yesterday 10:42" or "Mon 3 Nov 10:42", in the computer's own clock.
export function runWhen(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  const days = Math.round((startOfDay(now).getTime() - startOfDay(d).getTime()) / 86_400_000)
  const day = days === 0 ? 'Today' : days === 1 ? 'Yesterday' : `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`
  return `${day} ${clock(d)}`
}

// "Today 10:42, after 3 files were added: sorted 2, asked 1"; "suggested" instead of "sorted" in suggest mode.
export function runTitle(run: ReviewDetail, now: Date = new Date()): string {
  const sorted = run.decisions.filter(d => d.status === 'applied' && !d.reverses).length
  const suggested = run.decisions.filter(d => d.status === 'suggested').length
  const asked = run.questions.length
  const parts = [
    sorted ? `sorted ${sorted}` : '',
    suggested ? `suggested ${suggested}` : '',
    asked ? `asked ${asked}` : '',
  ].filter(Boolean)
  const head = [runWhen(run.started_at, now), run.trigger_summary].filter(Boolean).join(', ')
  // A review still running has not yet found nothing: it says what it has done so far, or only when it started.
  if (!parts.length && run.status === 'running') return head
  return `${head}: ${parts.length ? parts.join(', ') : 'Nothing to change.'}`
}

// The Overview's line about the last run; null when the client has had none.
export function overviewReviewLine(lastRunAt: string | null, unseen: number): string | null {
  if (!lastRunAt) return null
  return `AI review: last run ${clock(new Date(lastRunAt))}. ${unseen} ${unseen === 1 ? 'change' : 'changes'} you haven't looked at`
}

// The changes the person hasn't looked at, as the server counts them for the clients list: what unseen finished
// runs applied (an undo is not one of them) or suggested.
export const unseenChanges = (runs: ReviewDetail[]): number =>
  runs.filter(r => !r.seen && r.status === 'done').reduce((n, r) =>
    n + r.decisions.filter(d => (d.status === 'applied' && !d.reverses) || d.status === 'suggested').length, 0)

// Whether a change in this run has been undone: another decision of the run reverses it.
export const isReversed = (run: ReviewDetail, decisionId: string): boolean => run.decisions.some(d => d.reverses === decisionId)

// The runs, newest first.
export const newestFirst = (runs: ReviewDetail[]): ReviewDetail[] =>
  [...runs].sort((a, b) => (a.started_at < b.started_at ? 1 : a.started_at > b.started_at ? -1 : 0))

// ─── The AI review page: its notice and its history. Runs are given newest first. ───

const sameDay = (a: Date, b: Date) => startOfDay(a).getTime() === startOfDay(b).getTime()

// What stands in the way of a review, said once at the top of the page: one is running, the newest runs failed
// (however many in a row, with the newest's error, and Try again), or reviews are paused or off. None otherwise.
export interface ReviewNotice { kind: 'reviewing' | 'failed' | 'limited' | 'off'; text: string; retry: boolean }
export function reviewNotice(runs: ReviewDetail[], now: Date = new Date()): ReviewNotice | null {
  const newest = runs[0]
  if (!newest || newest.status === 'done') return null
  if (newest.status === 'running') return { kind: 'reviewing', retry: false, text: 'Reviewing…' }
  if (newest.status === 'limited') return { kind: 'limited', retry: false, text: 'AI review is paused for today: limit reached.' }
  if (newest.status === 'off') return { kind: 'off', retry: false, text: 'AI review is off for this client.' }
  const streak = runs.findIndex(r => r.status !== 'failed')
  const tries = streak < 0 ? runs.length : streak
  const since = runWhen(runs[tries - 1].started_at, now)
  return {
    kind: 'failed', retry: true,
    text: `The review hasn't finished since ${since}${newest.error ? `: ${newest.error}` : ''} (${tries} ${tries === 1 ? 'try' : 'tries'}).`,
  }
}

// How many changes a run tried that the checks stopped: they were never made, so only their number is said.
export const refusedLine = (n: number): string =>
  `${n} other change${n === 1 ? '' : 's'} the AI tried ${n === 1 ? 'was' : 'were'} stopped by the checks and not made.`

// One line for each run, newest first: when, what set it off and what it did. Runs that failed one after another
// with the same error are one line.
export interface ActivityLine { key: string; text: string; failed: boolean }
export function activityLines(runs: ReviewDetail[], now: Date = new Date()): ActivityLine[] {
  const lines: ActivityLine[] = []
  for (let i = 0; i < runs.length; i++) {
    const run = runs[i]
    const when = runWhen(run.started_at, now)
    if (run.status === 'limited') lines.push({ key: run.id, failed: false, text: `${when}: paused for today: limit reached` })
    else if (run.status === 'off') lines.push({ key: run.id, failed: false, text: `${when}: AI review is off for this client` })
    else if (run.status === 'failed') {
      let last = i
      while (runs[last + 1]?.status === 'failed' && runs[last + 1].error === run.error) last++
      const why = run.error ? `: ${run.error}` : ''
      if (last === i) {
        lines.push({ key: run.id, failed: true, text: `${[when, run.trigger_summary].filter(Boolean).join(', ')} · didn't finish${why}` })
      } else {
        const [from, to] = [new Date(runs[last].started_at), new Date(run.started_at)]
        const until = sameDay(from, to) ? clock(to) : when
        lines.push({ key: run.id, failed: true,
                     text: `${runWhen(runs[last].started_at, now)} to ${until} · ${last - i + 1} runs didn't finish${why}` })
        i = last
      }
    } else {
      const title = runTitle(run, now)
      const refused = run.decisions.filter(d => d.status === 'refused').length
      lines.push({ key: run.id, failed: false, text: refused ? `${title}${title.endsWith('.') ? '' : '.'} ${refusedLine(refused)}` : title })
    }
  }
  return lines
}

// Every change a review made that still stands, newest run first: not a refused or suggested one, not an undo, and
// not one that was undone (reversed: the ids some decision reverses). fresh: its run had not been looked at when the
// page opened (freshRuns).
export interface AiChange { decision: Decision; fresh: boolean }
export function aiChanges(runs: ReviewDetail[], reversed: Set<string>, freshRuns: Set<string>): AiChange[] {
  return runs.filter(r => r.status === 'done' || r.status === 'running').flatMap(run =>
    run.decisions.filter(d => d.status === 'applied' && !d.reverses && !reversed.has(d.id) && !isReversed(run, d.id))
      .map(decision => ({ decision, fresh: freshRuns.has(run.id) })))
}

// When the books were last reviewed to the end; null when no review has finished.
export function lastReviewed(runs: ReviewDetail[], now: Date = new Date()): string | null {
  const done = runs.find(r => r.status === 'done')
  return done ? runWhen(done.started_at, now) : null
}
