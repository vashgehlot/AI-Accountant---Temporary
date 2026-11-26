// Rules the client pages share, kept apart from the network so node --test can run them.
import type { Transaction } from './api'
import type { AccountChoice, BankAccount, BankAccountKind, BusinessType, ClientFields, ClientSummary, EditableField, Owner, RowChange, SavedRow, StatementCheck,
              Upload } from './clients'
import { money, needsReview, totalsOf, vatBooked } from './ledger.ts'

export const BUSINESS_TYPES: Record<BusinessType, string> = {
  limited_company: 'Limited company', sole_trader: 'Sole trader', partnership: 'Partnership', llp: 'LLP',
}

export const DOCUMENT_TYPES: Record<string, string> = {
  receipt: 'Receipt', invoice: 'Invoice', expense_claim: 'Expense claim', statement: 'Bank statement line',
  agent_statement: "Agent's statement", payroll: 'Payroll report', journal: 'Journal',
  quote: 'Quote', pro_forma: 'Pro forma invoice', purchase_order: 'Purchase order',
  remittance_advice: 'Remittance advice', supplier_statement: "Supplier's statement",
  finance_agreement: 'Finance or loan agreement', other: 'Other document',
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

export const BANK_KINDS: Record<BankAccountKind, string> = {
  current: 'Current account', savings: 'Savings account', credit_card: 'Credit card', petty_cash: 'Petty cash',
}

// How many of each kind the chart has codes for (1200 to 1202, 1210 and 1211, 1240 and 1241, 1230).
const BANK_LIMITS: Record<BankAccountKind, number> = { current: 3, savings: 2, credit_card: 2, petty_cash: 1 }

export const bankAccountsLeft = (accounts: BankAccount[], kind: BankAccountKind) =>
  BANK_LIMITS[kind] - accounts.filter(a => a.kind === kind).length

// What a business's owners are called, by its kind; a sole trader lists none. Up to four, as the chart has accounts for.
export const OWNER_WORDS: Partial<Record<BusinessType, string>> = { limited_company: 'director', partnership: 'partner', llp: 'member' }
export const MAX_OWNERS = 4

// What is wrong with a business's owners, as the API says it (ledger.check_owners); '' when nothing is. Partners' and
// members' shares, when any is given, are given for each of them and add up to 100%.
export function ownerError(type: BusinessType, owners: Owner[] = []): string {
  const word = OWNER_WORDS[type]
  if (!word) return owners.length ? 'A sole trader has no directors, partners or members to list' : ''
  if (owners.length > MAX_OWNERS) return `You can list up to ${MAX_OWNERS} ${word}s`
  const names = owners.map(o => o.name.trim().toLowerCase())
  if (names.some(name => !name)) return `Name each ${word}`
  const twice = names.findIndex((name, i) => names.indexOf(name) !== i)
  if (twice >= 0) return `Two ${word}s are called ${owners[twice].name.trim()}: give each their own name`
  if (type === 'limited_company') return ''
  const shares = owners.map(o => (o.share ?? '').toString().trim())
  if (shares.every(share => !share)) return ''
  if (shares.some(share => !share || !(Number(share) > 0))) return `Give each ${word}'s share of the profit, above 0%`
  const total = shares.reduce((sum, share) => sum + Number(share), 0)
  return Math.abs(total - 100) > 1e-9 ? `The ${word}s' shares of the profit add up to ${total}%: make them 100%` : ''
}

// The owners as the API takes them: none for a sole trader, and each share sent as a number or none.
export const ownersToSend = (type: BusinessType, owners: Owner[] = []): Owner[] =>
  (OWNER_WORDS[type] ? owners.map(o => ({ ...o, name: o.name.trim(), share: (o.share ?? '').toString().trim() || null })) : [])

export type ClientErrors = Partial<Record<'name' | 'contact_name' | 'contact_email' | 'contact_phone' | 'first_year_end' | 'bank_accounts' | 'owners', string>>

// What the client dialog says before saving; the API checks the same.
// taken: the names of the other clients, so two are not given the same one by mistake.
export function clientFormErrors(fields: ClientFields, taken: string[] = []): ClientErrors {
  const errors: ClientErrors = {}
  if (!fields.name.trim()) errors.name = 'Enter the company name'
  else if (taken.some(name => name.trim().toLowerCase() === fields.name.trim().toLowerCase())) {
    errors.name = 'Another client already has this name'
  }
  // A phone number is digits, with spaces, brackets, dashes and a leading + allowed: seven digits or more.
  const phone = fields.contact_phone.trim()
  if (phone && (!/^\+?[\d\s()-]+$/.test(phone) || phone.replace(/\D/g, '').length < 7)) {
    errors.contact_phone = 'Enter a valid phone number'
  }
  if (!fields.contact_name.trim()) errors.contact_name = 'Enter the responsible person'
  if (fields.contact_email.trim() && !fields.contact_email.includes('@')) errors.contact_email = 'Enter a valid email'
  if (!fields.first_year_end) errors.first_year_end = "Enter the client's first year end"
  const names = fields.bank_accounts.map(a => a.name.trim().toLowerCase())
  const twice = names.findIndex((name, i) => name && names.indexOf(name) !== i)
  if (!fields.bank_accounts.length) errors.bank_accounts = 'Add at least one bank account'
  else if (names.some(name => !name)) errors.bank_accounts = 'Name each bank account'
  else if (twice >= 0) errors.bank_accounts = `Two bank accounts are called ${fields.bank_accounts[twice].name.trim()}: give each its own name`
  const owners = ownerError(fields.business_type, fields.owners)
  if (owners && OWNER_WORDS[fields.business_type]) errors.owners = owners
  return errors
}

// The four figures at the top of a client's page.
export function figuresOf(rows: SavedRow[]) {
  const totals = totalsOf(rows)
  const owed = (key: string) => totals.find(t => t.key === key)?.stillOwed ?? '0.00'
  return {
    rows: rows.length,
    toReview: rows.filter(row => needsReview(row)).length,
    toPay: owed('documents-out'),
    toReceive: owed('documents-in'),
  }
}

// The saved upload a picked file repeats, by its fingerprint.
export const sameFileAs = (hash: string | null, uploads: Upload[]) =>
  (hash ? uploads.find(upload => upload.sha256 === hash) : undefined)

// A file picked for upload, and how far it got: waiting to be sent, being sent, sent and being read, and so on.
export type FileStatus = 'waiting' | 'sending' | 'reading' | 'done' | 'failed' | 'skipped' | 'cancelled'

export interface PickedFile {
  id: number
  file: File
  hash: string | null      // fingerprint of the file's content (null if the browser cannot hash)
  status: FileStatus
  detail: string
  jobId?: string           // the API's job reading it, once it has been sent
}

// Whether files are still to be sent to the API: leaving the page now would lose them. Once sent, a file is read and
// saved by the API whatever the page does.
export const unsent = (items: PickedFile[]) => items.some(item => item.status === 'waiting' || item.status === 'sending')

// A file the API is reading for the client now, as GET /api/clients/{id}/reading lists it.
export interface ReadingFile {
  job_id: string
  name: string
  status: 'queued' | 'running'
  progress: string
  year_start: string | null
}

// Whether a file listed as being read before is no longer: it has been saved (or failed), so the year is fetched again.
export const someFinished = (before: ReadingFile[], now: ReadingFile[]) =>
  before.some(file => !now.some(next => next.job_id === file.job_id))

// How far a file being read has got.
export const readingLine = (file: ReadingFile) => (file.status === 'queued' ? 'Waiting its turn' : file.progress || 'Reading…')

// How many transactions an upload holds or a file gave: "1 transaction", "12 transactions".
export const transactionCount = (n: number) => `${n} transaction${n === 1 ? '' : 's'}`

// The question asked before several files are removed together.
export const removeUploadsText = (uploads: Upload[]) => {
  const rows = uploads.reduce((n, u) => n + u.rows, 0)
  return `Remove ${uploads.length} file${uploads.length === 1 ? '' : 's'} and their ${transactionCount(rows)}? ` +
    "This can't be undone: analyse the files again to get them back."
}

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
    document_type: row.document_type ?? 'receipt', vat_treatment: row.vat_treatment ?? '',
  }
}

// What Edit says under its VAT box when the row books VAT its document doesn't print (worked out from the total, at
// the rate a person chose or the account's), so an empty box doesn't read as no VAT; null when it prints its VAT or
// none is booked. The box holds only a VAT amount the document prints.
export function vatWorkedOut(row: Transaction): string | null {
  const booked = vatBooked(row)
  if (row.vat != null || !(Number(booked) > 0)) return null
  const kind = (DOCUMENT_TYPES[row.document_type ?? 'receipt'] ?? 'document').toLowerCase()
  return `${money(booked)} VAT is booked, worked out from the total: the ${kind} prints no VAT amount. Leave this empty to keep it.`
}

// How VAT applies to a row, as a person can say it. '' leaves it to the document and the account.
export const VAT_TREATMENTS: Record<string, string> = {
  '': 'As the document shows', standard: 'Standard rate (20%)', reduced: 'Reduced rate (5%)', zero: 'Zero-rated',
  exempt: 'Exempt', outside_scope: 'Outside the scope (reverse charge, overseas)',
}

// What can have paid a receipt (or taken its money in): each of the client's accounts by its name, then whoever paid
// it themselves: an owner (their Director's Loan Account in a company, their Capital Introduced otherwise), each by
// name when they are listed, or staff to repay.
export function paidFromOptions(client: Pick<ClientFields, 'business_type' | 'bank_accounts' | 'owners'>): { code: string; name: string }[] {
  const company = client.business_type === 'limited_company'
  const code = (slot: number) => `${company ? 225 : 301}${slot}`
  const listed = (client.owners ?? []).filter(o => o.slot !== null && o.slot !== undefined)
  return [
    ...client.bank_accounts.map(a => ({ code: a.code ?? '', name: a.name })).filter(a => a.code),
    ...(listed.length ? listed.map(o => ({ code: code(o.slot as number), name: `${o.name}'s own money or card` }))
      : [company ? { code: '2250', name: "The director's own money or card" } : { code: '3010', name: "The owner's own money or card" }]),
    { code: '2110', name: 'Staff, to be repaid' },
  ]
}

// The account a saved receipt is paid from now: the one a person chose, else the client's main (first current) account.
export function paidFromOf(row: Transaction, client: Pick<ClientFields, 'bank_accounts'>): string {
  const main = client.bank_accounts.find(a => a.kind === 'current') ?? client.bank_accounts[0]
  return row.bank_account ?? main?.code ?? ''
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
    document_type: draft.document_type, ...(draft.vat_treatment ? { vat_treatment: draft.vat_treatment } : {}), ...(joins ? { document_ref: template.document_ref } : {}),
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
    change[field] = value === '' && (field === 'date' || field === 'vat' || field === 'counterparty' || field === 'vat_treatment') ? null : value
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

// What a closed year's sections say in place of their controls.
export const CLOSED_YEAR_NOTICE = 'This year is closed. Reopen it from Trial balance to change it.'
