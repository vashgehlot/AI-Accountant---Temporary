// Rules the client pages share, kept apart from the network so node --test can run them.
import type { Transaction } from './api'
import type { AccountChoice, BusinessType, ClientFields, ClientSummary, EditableField, RowChange, SavedRow, StatementCheck,
              Upload } from './clients'
import { money, totalsOf } from './ledger.ts'

export const BUSINESS_TYPES: Record<BusinessType, string> = {
  limited_company: 'Limited company', sole_trader: 'Sole trader', partnership: 'Partnership', llp: 'LLP',
}

export const DOCUMENT_TYPES: Record<string, string> = {
  receipt: 'Receipt', invoice: 'Invoice', expense_claim: 'Expense claim', statement: 'Bank statement line',
  agent_statement: "Agent's statement",
  quote: 'Quote', pro_forma: 'Pro forma invoice', purchase_order: 'Purchase order',
  remittance_advice: 'Remittance advice', supplier_statement: "Supplier's statement", other: 'Other document',
}

// "6 Oct", from an ISO date or time.
export function dayMonth(iso: string | null | undefined): string {
  if (!iso) return ''
  const when = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso)
  return Number.isNaN(when.getTime()) ? '' : when.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

// The clients whose company, responsible person or email holds the search text, ignoring case.
export function searchClients(clients: ClientSummary[], query: string): ClientSummary[] {
  const wanted = query.trim().toLowerCase()
  if (!wanted) return clients
  return clients.filter(c => [c.name, c.contact_name, c.contact_email].some(text => text.toLowerCase().includes(wanted)))
}

// The first page invites you to add a client only when there are none at all: with every client archived,
// the list (and Show archived) must stay, or nothing could be restored.
export const showsInvitation = (counts: { active: number; archived: number }, showArchived: boolean) =>
  !showArchived && counts.active === 0 && counts.archived === 0

// What the clients table says when it has no rows to show.
export function emptyListText(showArchived: boolean, query: string): string {
  if (query.trim()) return 'No clients match your search.'
  return showArchived ? 'No archived clients.' : 'No active clients. Show archived to restore one.'
}

export type ClientErrors = Partial<Record<'name' | 'contact_name' | 'contact_email', string>>

// What the client dialog says before saving; the API checks the same.
export function clientFormErrors(fields: ClientFields): ClientErrors {
  const errors: ClientErrors = {}
  if (!fields.name.trim()) errors.name = 'Enter the company name'
  if (!fields.contact_name.trim()) errors.contact_name = 'Enter the responsible person'
  if (fields.contact_email.trim() && !fields.contact_email.includes('@')) errors.contact_email = 'Enter a valid email'
  return errors
}

// The four figures at the top of a client's page.
export function figuresOf(rows: SavedRow[]) {
  const totals = totalsOf(rows)
  const owed = (key: string) => totals.find(t => t.key === key)?.stillOwed ?? '0.00'
  return {
    rows: rows.length,
    toReview: rows.filter(row => row.issues.some(i => i.severity === 'error' || i.severity === 'warning')).length,
    toPay: owed('documents-out'),
    toReceive: owed('documents-in'),
  }
}

// The saved upload a picked file repeats, by its fingerprint.
export const sameFileAs = (hash: string | null, uploads: Upload[]) =>
  (hash ? uploads.find(upload => upload.sha256 === hash) : undefined)

// A file picked for upload, and how far it got.
export type FileStatus = 'waiting' | 'reading' | 'done' | 'failed' | 'skipped' | 'cancelled'

export interface PickedFile {
  id: number
  file: File
  hash: string | null      // fingerprint of the file's content (null if the browser cannot hash)
  status: FileStatus
  detail: string
}

// How many transactions an upload holds or a file gave: "1 transaction", "12 transactions".
export const transactionCount = (n: number) => `${n} transaction${n === 1 ? '' : 's'}`

// Why a file that repeats a saved upload is not read again.
export const sameFileText = (upload: Upload) => `Skipped: same file as ${upload.name}, uploaded ${dayMonth(upload.created_at)}`

// The files Retry reads again: those that failed or were cancelled, unless the file was saved after all (a job
// can save its rows just as a cancel arrives); those are skipped like any file uploaded before.
export function requeue(items: PickedFile[], uploads: Upload[]): PickedFile[] {
  return items.map(item => {
    if (item.status !== 'failed' && item.status !== 'cancelled') return item
    const saved = sameFileAs(item.hash, uploads)
    return saved ? { ...item, status: 'skipped', detail: sameFileText(saved) } : { ...item, status: 'waiting', detail: 'Waiting' }
  })
}

// What the uploads list says about a bank statement's balances; null for any other upload.
export function statementText(check: StatementCheck | null): string | null {
  if (!check) return null
  if (check.status === 'ok') return 'Balances add up'
  if (check.status === 'gap') return `Doesn't add up: ${money(check.difference)}`
  return 'No balances to check'
}

// The edit form's fields, as text.
export type EditDraft = Record<EditableField, string>
export type EditErrors = Partial<Record<EditableField, string>>

export function draftOf(row: Transaction): EditDraft {
  return {
    date: row.date ?? '', description: row.description, counterparty: row.counterparty ?? '',
    direction: row.direction, gross: row.gross, vat: row.vat ?? '', account_code: row.account_code,
    document_type: row.document_type ?? 'receipt',
  }
}

// The form for a row a person adds: blank, or a line of an existing document (a claim, an invoice) that joins it,
// with its type, counterparty, date, direction and account to start from.
export function lineTemplate(of: Transaction | null): Transaction {
  const blank = { date: null, description: '', counterparty: null, direction: 'out', gross: '', vat: null,
                  account_code: '', document_type: 'receipt' }
  return (of ? { ...blank, date: of.date, counterparty: of.counterparty ?? null, direction: of.direction,
                 account_code: of.account_code, document_type: of.document_type ?? 'receipt',
                 document_ref: of.document_ref ?? null }
             : blank) as unknown as Transaction
}

// The row a person added, as the API takes it: a line of the template's document while it keeps its type.
export function newRowFrom(draft: EditDraft, template: Transaction): Transaction {
  const text = (value: string) => value.trim() || null
  const joins = template.document_ref && draft.document_type === template.document_type
  return {
    date: text(draft.date), description: draft.description.trim(), counterparty: text(draft.counterparty),
    direction: draft.direction, gross: draft.gross.trim(), vat: text(draft.vat), account_code: draft.account_code,
    document_type: draft.document_type, ...(joins ? { document_ref: template.document_ref } : {}),
  } as unknown as Transaction
}

// What the edit form says before saving; the API checks the same.
export function rowEditErrors(draft: EditDraft): EditErrors {
  const errors: EditErrors = {}
  const gross = Number(draft.gross)
  const vat = draft.vat.trim() === '' ? null : Number(draft.vat)
  if (!draft.description.trim()) errors.description = 'Enter a description'
  if (!draft.account_code) errors.account_code = 'Choose an account'
  if (draft.date && !/^\d{4}-\d{2}-\d{2}$/.test(draft.date)) errors.date = 'Enter a date'
  if (!draft.gross.trim() || !Number.isFinite(gross) || gross <= 0) errors.gross = 'Enter an amount above zero'
  if (vat !== null && (!Number.isFinite(vat) || vat < 0)) errors.vat = "VAT can't be negative"
  else if (vat !== null && !errors.gross && vat >= gross) errors.vat = 'VAT must be below the amount'
  return errors
}

// Only what the person changed, with empty text sent as none (no date, no VAT shown, no counterparty).
export function changesOf(row: Transaction, draft: EditDraft): RowChange {
  const before = draftOf(row)
  const change: RowChange = {}
  for (const field of Object.keys(draft) as EditableField[]) {
    const value = draft[field].trim()
    const was = before[field].trim()
    const sameAmount = (field === 'gross' || field === 'vat') && value !== '' && was !== '' && Number(value) === Number(was)
    if (value === was || sameAmount) continue
    change[field] = value === '' && (field === 'date' || field === 'vat' || field === 'counterparty') ? null : value
  }
  return change
}


// The Edit list of accounts, in name order (they show without their codes). The row's saved account stays listed,
// first, while it is chosen and this kind of business can't choose it, so the form shows the truth; an account not in
// the chart has no name.
export function accountList(accounts: AccountChoice[], saved: { code: string; name: string | null | undefined },
                            current: string): AccountChoice[] {
  const sorted = [...accounts].sort((a, b) => a.name.localeCompare(b.name, 'en-GB'))
  return !saved.code || accounts.some(a => a.code === current) ? sorted
    : [{ code: saved.code, name: saved.name || 'Unknown account', type: '', vat: '' }, ...sorted]
}
