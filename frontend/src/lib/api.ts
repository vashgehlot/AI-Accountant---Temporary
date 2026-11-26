// Client for the LedgerSync API. Paths are relative so every request goes through the
// Next.js rewrite in next.config.ts: no CORS and no hardcoded host.

export interface Issue {
  code: string
  message: string
  severity: 'info' | 'warning' | 'error'
  related?: number[]   // the other rows it is about, by row id (Show both)
  about?: 'row' | 'document'   // what it is a problem with: the row (when absent too), or its whole document
  difference?: string | null   // a total that doesn't add up: what it is out by (positive: short; negative: over)
}

export interface Settlement {
  ref: string
  amount: string
  date: string | null
  description: string
  kind?: string | null      // the kind of document or line it is: what was paid, or what paid (an agent's statement)
}

export interface Transaction {
  date: string | null
  description: string
  direction: 'in' | 'out'
  gross: string
  vat: string | null            // VAT shown on the document; null = not shown (the API then books none)
  vat_treatment: string | null  // rate a person picked, to estimate VAT not shown; null = none picked
  vat_posted: string | null     // set by the API: the VAT the ledger books
  net: string | null            // set by the API: gross minus vat_posted
  // Set by the API: the part of vat_posted the books do not reclaim (the row is held in Suspense for its VAT
  // invoice, or its document isn't a VAT invoice), and why. The books hold the whole amount with no VAT.
  vat_not_reclaimed?: string | null
  vat_confirmed?: boolean           // a person entered the VAT, or said to reclaim it: reclaimed on their say
  vat_from_claim?: boolean          // set by the API: its VAT is what its expense claim shows, its receipt showing none
  vat_not_reclaimed_why?: string | null
  account_code: string
  account_name?: string | null
  contra_account_name?: string | null   // the name of the other side: a journal's credit account
  contra_account_code: string | null
  bank_account?: string | null      // a bank line: the account or card its statement is for
  currency: string
  source: string
  method: string
  evidence: string | null
  issues: Issue[]
  document_type?: string             // receipt, invoice, expense_claim, statement, or one that is not a transaction
  counterparty?: string | null
  document_number?: string | null    // the invoice, receipt or claim number printed on the document
  agent?: string | null              // on an agent's statement: the agent, who holds what it collected
  document_ref?: string | null       // shared by the rows of one document
  include?: boolean                  // a person's tick on a document that is not a transaction
  link?: string[] | null             // a person's decision on a bank line: null automatic, [] none, refs: pays these
  paid_against?: string | null       // set by the API: the account a matched bank line settles
  paid_against_name?: string | null
  pays?: Settlement[]                // set by the API on a bank line
  candidates?: Settlement[][]        // set by the API: options for the Link buttons
  owed?: string | null               // set by the API on a document's row: what is still open on it
  document_direction?: 'in' | 'out' | null  // set by the API on a document's row: in when they owe the business
  paid_by?: Settlement[]             // set by the API on a document's row
  copy_of?: Settlement | null        // set by the API: the earlier document this one repeats; not booked unless included
  recorded_by?: Settlement | null    // set by the API: the receipt or invoice for this bank or claim line, booked instead
  claimed_in?: Settlement | null     // set by the API on a receipt or invoice: the expense claim it is owed on
  recorded_by_refs?: string[]        // set by the API on a claim line booked from several receipts of one document:
                                     // each one's ref (recorded_by then stands for them all)
  left_off_claim?: Settlement | null // set by the API on a receipt of that document the claim leaves out: the claim;
                                     // the claimant paid it, so not booked unless included
  document_total?: string | null     // the total printed on its document, which the API checks the rows against
  document_net?: string | null       // the total before VAT printed on its document
  not_vat_invoice?: boolean          // its document says it is not a VAT invoice
  vat_found?: string | null          // set by the API on a receipt on a claim: VAT its prices and the claim agree on,
                                     // not booked because it is not a VAT invoice (Book VAT)
  date_found?: string | null         // set by the API: the date of the row's other record (its claim line, receipt or
                                     // card payment) when it agrees on all but the date (Use)
  amount_found?: string | null       // set by the API: that record's amount, when the two agree on the shop and the day (Use)
  apart_from?: number[]              // rows a person said are not the same as this one, by row id (Not the same)
  accepted?: string[]                // warnings a person said are fine, by code (It's fine)
  reverse_charge?: boolean           // a service from abroad with no VAT charged: the VAT is due and reclaimed
  without_document?: string | null   // a person booked it without its receipt or invoice, for this reason
  excluded?: boolean                 // a decision left it out of the books
  removed?: boolean                  // a person removed it: out of the books (excluded too) until they Put back
  total_accepted?: string | null     // the difference from its document's total a person said to leave as it is
  superseded_by?: string | null      // the decision that replaced it with other rows
  decision_ids?: string[]            // the decisions that changed it
}

export interface AnalyzeResult {
  transactions: Transaction[]
  warnings: string[]
  model: string | null
  client_id?: number    // set when the analysis was for a client: its rows were saved
  upload_id?: number
}

export interface TrialBalanceLine {
  code: string
  name: string
  type: string
  heading?: string      // where it goes in the accounts, such as 'Tangible assets'; missing from older APIs
  debit: string
  credit: string
}

export interface TrialBalanceResult {
  lines: TrialBalanceLine[]       // the closing balances: the opening balances plus the year's movements
  opening?: TrialBalanceLine[]    // the opening balances alone; missing from older APIs
  total_debits: string
  total_credits: string
  is_balanced: boolean
  total_income?: string
  total_expenses?: string
  net_profit?: string
  total_assets?: string
  total_liabilities?: string
  left_out?: string[]             // rows with a problem to fix, left out of these figures, each named in words
}

export interface Health {
  model: string
  ai_reachable: boolean
  model_available: boolean
  ai_error: string | null
  max_upload_mb: number
  max_parallel_jobs?: number    // files the API reads at once; missing from older APIs
  demo?: boolean                // LEDGERSYNC_DEMO=1: the header offers Reset demo
}

interface Job {
  job_id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  progress: string
  result: AnalyzeResult | null
  error: { code: string; message: string } | null
}

export class ApiError extends Error {
  code: string

  constructor(message: string, code: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

const POLL_INTERVAL_MS = 1_000
const MAX_POLL_FAILURES = 10 // ~10 s: long enough for the API to restart
const API_DOWN = 'Super Accountant could not be reached. Try again in a moment; if it keeps happening, the person who runs it needs to check the server is up.'

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

export async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const res = await fetch(path, { ...init, signal: controller.signal })
    .catch(() => {
      throw controller.signal.aborted
        ? new ApiError('The Super Accountant API did not respond in time.', 'timeout')
        : new ApiError('Super Accountant could not be reached. Try again in a moment; if it keeps happening, the person who runs it needs to check the server is up.', 'network')
    })
    .finally(() => clearTimeout(timer))
  if (!res.ok) throw await errorFrom(res)
  if (res.status === 204) return undefined as T     // done, with nothing to read back
  return (await res.json()) as T
}

export async function errorFrom(res: Response): Promise<ApiError> {
  let detail: unknown
  try {
    detail = (await res.json()).detail
  } catch {
    // Not JSON: the Next proxy answers a plain "Internal Server Error" when the API is down.
    if (res.status >= 500) return new ApiError(API_DOWN, 'network')
    detail = undefined
  }
  const code = `http_${res.status}`
  if (typeof detail === 'string') return new ApiError(detail, code)
  if (Array.isArray(detail)) {
    return new ApiError(detail.map(d => (d as { msg?: string }).msg ?? String(d)).join('; '), code)
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const d = detail as { message: string; code?: string }
    return new ApiError(d.message, d.code ?? code)
  }
  return new ApiError(`The Super Accountant API returned HTTP ${res.status}.`, code)
}

export function getHealth(): Promise<Health> {
  return request<Health>('/api/health', {}, 10_000)
}

// The form /api/analyze takes: one file or some pasted text. For a client's documents it also names the client, the
// year they go to and the bank account a statement is on; the API refuses a statement without an account when the
// client has several.
export function analysisForm(source: { file?: Blob; text?: string },
                             where?: { clientId: number; yearStart: string; bankAccount: string }): FormData {
  const data = new FormData()
  if (source.file) data.append('file', source.file)
  if (source.text !== undefined) data.append('text', source.text)
  if (where) {
    data.append('client_id', String(where.clientId))
    data.append('year_start', where.yearStart)
    if (where.bankAccount) data.append('bank_account', where.bankAccount)
  }
  return data
}

// Starts an analysis job and polls it until it finishes, reporting progress along the way.
// isCancelled is checked between polls. Cancelling asks the server to stop the job, then waits for the job's
// own answer: a job that saved a client's rows before the cancel arrived still succeeds, and calling it
// cancelled would invite booking the same file twice.
export async function analyze(
  formData: FormData,
  onProgress: (progress: string) => void,
  isCancelled: () => boolean,
): Promise<AnalyzeResult> {
  return waitForJob(await startAnalysis(formData), onProgress, isCancelled)
}

// Sends an input to be analysed and returns its job's id at once: the API reads it and, for a client, saves its rows
// whatever the page does next, so a refresh after this loses nothing.
export async function startAnalysis(formData: FormData): Promise<string> {
  // The API takes analyses only with this header, which a form on another web site can't send.
  const init = { method: 'POST', body: formData, headers: { 'X-LedgerSync': '1' } }
  const { job_id } = await request<{ job_id: string }>('/api/analyze', init, 120_000)
  return job_id
}

// Polls a job (one analyze started) until it finishes.
export async function waitForJob(
  job_id: string,
  onProgress: (progress: string) => void,
  isCancelled: () => boolean,
): Promise<AnalyzeResult> {
  let failures = 0
  let cancelSent = false
  for (;;) {
    if (isCancelled() && !cancelSent) {
      cancelSent = true
      onProgress('Cancelling…')
      await request(`/api/jobs/${job_id}`, { method: 'DELETE' }).catch(() => undefined)
    }
    let job: Job
    try {
      job = await request<Job>(`/api/jobs/${job_id}`)
      failures = 0
    } catch (e) {
      // The API may be restarting: keep polling briefly. Once it is back, an unknown
      // job answers 404 job_not_found with "please run it again".
      if (e instanceof ApiError && e.code === 'network' && ++failures < MAX_POLL_FAILURES) {
        onProgress('Waiting for the Super Accountant API…')
        await sleep(POLL_INTERVAL_MS)
        continue
      }
      throw e
    }
    if (job.status === 'succeeded' && job.result) return job.result
    if (job.status === 'failed') throw new ApiError(job.error?.message ?? 'Analysis failed.', job.error?.code ?? 'failed')
    if (job.status === 'cancelled') throw new ApiError('Analysis cancelled.', 'cancelled')
    if (!cancelSent) onProgress(job.progress)
    await sleep(POLL_INTERVAL_MS)
  }
}

export function validateTransactions(transactions: Transaction[]): Promise<{ transactions: Transaction[] }> {
  return request<{ transactions: Transaction[] }>('/api/transactions/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transactions }),
  })
}

export function trialBalance(transactions: Transaction[]): Promise<TrialBalanceResult> {
  return request<TrialBalanceResult>('/api/trial-balance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transactions }),
  })
}

// What the client pages show of the accountant chat, read from its routes (the types are in chat.ts).
export const getMateriality = (clientId: number, yearStart: string) =>
  request<import('./ledger.ts').Levels | null>(`/api/clients/${clientId}/years/${yearStart}/materiality`)
export const clientDecisions = (clientId: number, yearStart: string) =>
  request<import('./chat.ts').Decision[]>(`/api/clients/${clientId}/decisions?year_start=${yearStart}`)
export const postedTrialBalance = (clientId: number, yearStart: string) =>
  request<import('./chat.ts').PostedTrialBalance>(`/api/clients/${clientId}/years/${yearStart}/posted-trial-balance`)
