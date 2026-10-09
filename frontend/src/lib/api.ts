// Client for the LedgerSync API. Paths are relative so every request goes through the
// Next.js rewrite in next.config.ts: no CORS and no hardcoded host.

export interface Issue {
  code: string
  message: string
  severity: 'info' | 'warning' | 'error'
  related?: number[]   // the other rows it is about, by row id (Show both)
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
  account_code: string
  account_name?: string | null
  contra_account_code: string | null
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
  document_total?: string | null     // the total printed on its document, which the API checks the rows against
  document_net?: string | null       // the total before VAT printed on its document
  not_vat_invoice?: boolean          // its document says it is not a VAT invoice
  vat_found?: string | null          // set by the API on a receipt on a claim: VAT its prices and the claim agree on,
                                     // not booked because it is not a VAT invoice (Book VAT)
  date_found?: string | null         // set by the API: the date of the row's other record (its claim line, receipt or
                                     // card payment) when it agrees on all but the date (Use)
  amount_found?: string | null       // set by the API: that record's amount, when the two agree on the shop and the day (Use)
  apart_from?: number[]              // rows a person said are not the same as this one, by row id (Not the same)
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
  debit: string
  credit: string
}

export interface TrialBalanceResult {
  lines: TrialBalanceLine[]
  total_debits: string
  total_credits: string
  is_balanced: boolean
  total_income?: string
  total_expenses?: string
  net_profit?: string
  total_assets?: string
  total_liabilities?: string
}

export interface Health {
  model: string
  ai_reachable: boolean
  model_available: boolean
  ai_error: string | null
  max_upload_mb: number
  max_parallel_jobs?: number    // files the API reads at once; missing from older APIs
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
const API_DOWN = 'The Super Accountant API is not running or failed. Check that `python server.py` is running and see its log.'

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

export async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const res = await fetch(path, { ...init, signal: controller.signal })
    .catch(() => {
      throw controller.signal.aborted
        ? new ApiError('The Super Accountant API did not respond in time.', 'timeout')
        : new ApiError('Cannot reach the Super Accountant API. Is `python server.py` running?', 'network')
    })
    .finally(() => clearTimeout(timer))
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()) as T
}

async function errorFrom(res: Response): Promise<ApiError> {
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

// Starts an analysis job and polls it until it finishes, reporting progress along the way.
// isCancelled is checked between polls. Cancelling asks the server to stop the job, then waits for the job's
// own answer: a job that saved a client's rows before the cancel arrived still succeeds, and calling it
// cancelled would invite booking the same file twice.
export async function analyze(
  formData: FormData,
  onProgress: (progress: string) => void,
  isCancelled: () => boolean,
): Promise<AnalyzeResult> {
  // The API takes analyses only with this header, which a form on another web site can't send.
  const init = { method: 'POST', body: formData, headers: { 'X-LedgerSync': '1' } }
  const { job_id } = await request<{ job_id: string }>('/api/analyze', init, 120_000)
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
