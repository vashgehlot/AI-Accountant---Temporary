// Calls for clients and their saved ledgers (design of 2026-10-06). Paths go through the Next rewrite,
// like every other call in api.ts.
import { request, type Settlement, type Transaction, type TrialBalanceResult } from './api'
import type { ReadingFile } from './clientRules'

export type BusinessType = 'limited_company' | 'sole_trader' | 'partnership' | 'llp'

export type BankAccountKind = 'current' | 'savings' | 'credit_card' | 'petty_cash'

export interface BankAccount {
  code: string               // its account in the chart; '' until the server gives it the next free one
  name: string
  kind: BankAccountKind
}

export type AiReviewMode = 'automatic' | 'suggest' | 'off'

// One of a company's directors, a partnership's partners or an LLP's members, each with accounts of their own.
export interface Owner {
  slot?: number | null       // which of the chart's owners' accounts are theirs (0 to 3); none until the server gives one
  name: string
  share?: string | null      // a partner's or member's share of the profit, in percent; '' or none: shared equally
}

export interface ClientFields {
  name: string
  business_type: BusinessType
  contact_name: string       // the responsible person: the client's own contact
  contact_email: string
  contact_phone: string
  vat_registered: boolean
  vat_from?: string | null   // the day the VAT registration started; '' or null: registered throughout
  first_year_end: string     // the end of the first year the books are kept for: "2026-03-31"
  bank_accounts: BankAccount[]
  owners?: Owner[]           // its directors, partners or members; none for a sole trader
  ai_review?: AiReviewMode   // what the background review may do; automatic when not given
  materiality?: string | null   // the firm's overall materiality in pounds; '' or null: worked out from the figures
  capitalise_from?: string | null   // its capitalisation threshold in pounds net; '' or null: none
  // The client's references, as its papers print them; '' when not known.
  company_number?: string
  utr?: string
  vat_number?: string
  paye_reference?: string
  nature_of_business?: string   // what the business does: a streaming subscription is a film company's cost
  sic_code?: string
}

export interface ClosedYear {
  start: string
  end: string
  closed_at: string
}

export interface Client extends ClientFields {
  id: number
  closed_years?: ClosedYear[]
  archived: boolean
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface ClientSummary extends Client {
  rows: number
  to_review: number          // rows with an error or a warning
  ai_unseen?: number         // changes from background reviews the person hasn't looked at
}

export interface StatementCheck {
  status: 'ok' | 'gap' | 'none'
  difference: string | null
}

export interface Upload {
  id: number
  name: string               // the file's name, "Pasted text" or "Manual entry"
  kind: string
  sha256: string             // the file's fingerprint, to skip a file uploaded before
  model: string
  warnings: string[]
  created_at: string
  rows: number
  statement: StatementCheck | null
  bank_account?: string | null   // the account or card its statement lines are on; null: the default bank
  year_start?: string | null     // the year it was added to, which its undated rows wait in
}

export type EditableField =
  'date' | 'description' | 'counterparty' | 'direction' | 'gross' | 'vat' | 'account_code' | 'document_type' | 'vat_treatment'

export interface SavedRow extends Transaction {
  id: number
  upload_id: number
  edited: boolean
  original: Partial<Record<EditableField | 'currency', string | null>> | null   // what was read, once a person edits
}

export interface Year {
  start: string              // "2025-04-01"
  end: string
  label: string              // "Year to 31 Mar 2026"
  closed: boolean
  changed_since_closed?: boolean   // a closed year whose rows now work out to other balances than it closed with
  rows?: number              // how many of the client's rows it holds
}

// One year of a client: its rows, and the uploads that hold them or were added to it.
export interface Ledger {
  client: Client
  year: Year
  years: Year[]
  uploads: Upload[]
  transactions: SavedRow[]
}

// A person's change to a row: Link or Include, an edit, or revert.
export type RowChange = Partial<Record<EditableField, string | null>> & {
  link?: string[] | null
  include?: boolean
  apart_from?: number[]
  without_document?: string | null   // book it without its receipt or invoice, for this reason; null: hold it again
  vat_confirmed?: boolean            // reclaim the row's VAT on the person's say; false: leave it to the rules again
  removed?: false                    // Put back a row the person removed
  total_accepted?: string | null     // leave its document's total out by this much; null: ask about it again (Undo)
  revert?: boolean
  currency?: string                  // 'GBP': the amount, read in another currency, is now in pounds
  bank_account?: string | null       // what paid a receipt: one of the client's accounts, or who paid it themselves
  accepted?: string[]                // the warnings a person said are fine, by code
  reverse_charge?: boolean           // a service from abroad with no VAT charged
}

// Money is a string everywhere below, like the rest of the API.
export interface OpeningLine {
  code: string
  debit: string
  credit: string
}

export interface OpenItem {
  id: string
  direction: 'in' | 'out'    // in: a customer owes the client; out: the client owes a supplier
  counterparty: string
  amount: string
  number: string | null
  date: string | null
}

export interface OpeningBalances {
  lines: OpeningLine[]
  unpaid: OpenItem[]
}

export interface InvoiceSummary {
  ref: string
  kind: 'sale' | 'purchase'
  counterparty: string | null
  number: string | null
  date: string | null
  total: string
  paid: string
  owed: string               // still owed after every payment matched to it, in any year
  owed_at_year_end: string   // what was owed on the year's last day: payments after it left out
  paid_by: Settlement[]
  brought_forward: boolean   // dated before the year and still owed when it started
  credit_note?: boolean      // the money goes the other way: its amounts are shown as minus
}

// A bank account's balance in the books against its latest statement of the year, both as the statement prints it.
export interface BankCheck {
  code: string
  name: string
  kind: BankAccountKind
  books: string
  statement: string | null
  statement_date: string | null
  difference: string | null  // books less statement
  left_out?: number          // rows with a problem to fix, which the books figure is worked out without
}

export interface YearSummary {
  year: Year
  rows: number
  to_review: number
  unpaid_sales: string
  unpaid_purchases: string
  bank: BankCheck[]
  trial_balance: 'balanced' | 'blocked'
  problems: string[]         // what stops the trial balance
  missing_paperwork?: string[]   // statements the books need and don't have, in words
  pointers?: string[]            // what an accountant would want to know, in words
}

export interface AccountChoice {
  code: string
  name: string
  type: string
  vat: string
}

const send = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const listClients = (archived = false) => request<ClientSummary[]>(`/api/clients?archived=${archived}`)
export const addClient = (fields: ClientFields) => request<Client>('/api/clients', send('POST', fields))
export const changeClient = (id: number, change: Partial<ClientFields> & { archived?: boolean }) =>
  request<Client>(`/api/clients/${id}`, send('PATCH', change))
export const getClient = (id: number) => request<Client>(`/api/clients/${id}`)

// The calls for one of a client's years take its start ("2025-04-01"). An unknown year is a 404.
const inYear = (id: number, start: string) => `/api/clients/${id}/years/${start}`
export const getYears = (id: number) => request<Year[]>(`/api/clients/${id}/years`)
export const getYearLedger = (id: number, start: string) => request<Ledger>(`${inYear(id, start)}/ledger`)
export const getYearTrialBalance = (id: number, start: string) =>
  request<TrialBalanceResult>(`${inYear(id, start)}/trial-balance?shown=true`)
// The nine boxes of a VAT return for a period of a year, as a guide: money as strings, like the rest of the API.
export interface VatFigures {
  start: string
  end: string
  box1: string; box2: string; box3: string; box4: string; box5: string
  box6: string; box7: string; box8: string; box9: string
  notes: string[]
}
export const getVatFigures = (id: number, start: string, from: string, to: string) =>
  request<VatFigures>(`${inYear(id, start)}/vat?period_start=${from}&period_end=${to}`)
export const getInvoices = (id: number, start: string) => request<InvoiceSummary[]>(`${inYear(id, start)}/invoices`)
export const getBankChecks = (id: number, start: string) => request<BankCheck[]>(`${inYear(id, start)}/bank`)
export const getSummary = (id: number, start: string) => request<YearSummary>(`${inYear(id, start)}/summary`)
export const closeYear = (id: number, start: string) => request<Client>(`${inYear(id, start)}/close`, { method: 'POST' })
export const reopenYear = (id: number, start: string) => request<Client>(`${inYear(id, start)}/reopen`, { method: 'POST' })
export const yearExportUrl = (id: number, start: string) => `${inYear(id, start)}/export.xlsx`
export const getOpening = (id: number) => request<OpeningBalances>(`/api/clients/${id}/opening-balances`)
export const putOpening = (id: number, opening: OpeningBalances) =>
  request<OpeningBalances>(`/api/clients/${id}/opening-balances`, send('PUT', opening))

export const setUploadBank = (id: number, uploadId: number, code: string) =>
  request<Ledger>(`/api/clients/${id}/uploads/${uploadId}`, send('PATCH', { bank_account: code }))
export const changeRow = (id: number, rowId: number, change: RowChange) =>
  request<Ledger>(`/api/clients/${id}/rows/${rowId}`, send('PATCH', change))
// Rows a person types in, added to the year start names: a row without a date waits in that year.
export const addManualRows = (id: number, transactions: Transaction[], yearStart: string, name = 'Manual entry') =>
  request<Ledger>(`/api/clients/${id}/uploads`,
                  send('POST', { name, kind: 'manual', transactions, year_start: yearStart }))
export const removeRow = (id: number, rowId: number) =>
  request<Ledger>(`/api/clients/${id}/rows/${rowId}`, { method: 'DELETE' })
export const removeUpload = (id: number, uploadId: number) =>
  request<Ledger>(`/api/clients/${id}/uploads/${uploadId}`, { method: 'DELETE' })
// The accounts a row of this client can be coded to: its own bank accounts and cards among them.
export const listAccounts = (clientId: number) => request<AccountChoice[]>(`/api/accounts?client_id=${clientId}`)
// The whole chart, with the accounts a row is never coded to (Debtors, Creditors, the reserves) that opening balances use.
export const listChart = () => request<AccountChoice[]>('/api/accounts')

// The files the API is reading for the client now, after a refresh as well: the page lists them until each is saved.
export const getReading = (clientId: number) => request<ReadingFile[]>(`/api/clients/${clientId}/reading`)
