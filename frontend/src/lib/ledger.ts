// What the table shows for each row and in its totals: how a row is booked, the status line under its
// description with the choices it offers a person, and the totals. Pure functions, tested in ledger.test.ts.
import type { Issue, Settlement, Transaction } from './api'
import type { RowChange } from './clients'
import type { PaymentRow } from './duplicates'

const fmt = (n: number) =>
  n === 0
    ? ''
    : `£${Math.abs(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// Money as the table shows it: £1,234.50, or a dash when unknown.
export const money = (value: string | null | undefined) => (value == null ? '—' : fmt(Number(value)) || '£0.00')

export const NOT_TRANSACTIONS: Record<string, string> = {
  quote: 'a quote', pro_forma: 'a pro forma invoice', purchase_order: 'a purchase order',
  remittance_advice: 'a remittance advice', supplier_statement: "a supplier's statement of account",
  other: 'a document that is not a transaction',
}

export type RowKind = 'document' | 'bank' | 'other' | 'not booked'

// How a row is booked: a document holding what is owed, a bank line, anything else paid when it
// happened, or not booked at all (a quote or the like, a copy of a document, or a claim line its receipt books,
// until a person ticks Include; a card payment, which its receipt books).
export const kindOf = (tx: Transaction): RowKind => {
  const type = tx.document_type ?? 'receipt'
  if (!tx.include && (tx.copy_of || tx.recorded_by)) return 'not booked'
  if (tx.claimed_in) return 'document'   // a receipt on an expense claim is owed to the claimant, not paid by the business
  if (type in NOT_TRANSACTIONS) return tx.include ? 'document' : 'not booked'
  if (type === 'invoice' || type === 'expense_claim' || type === 'agent_statement') return 'document'
  return type === 'statement' ? 'bank' : 'other'
}

// A row as the duplicate check sees it, with what matching already linked it to: what it pays or what paid it, the
// expense claim it is on, and the receipt or invoice that books it. Linked rows are never each other's duplicates.
export const paymentRowOf = (tx: Transaction & { upload_id: number; id?: number }): PaymentRow => ({
  sourceId: tx.upload_id, gross: tx.gross, direction: tx.direction, date: tx.date, kind: kindOf(tx), ref: tx.document_ref,
  linked: [...(tx.pays ?? []), ...(tx.paid_by ?? []), tx.claimed_in, tx.recorded_by]
    .filter((s): s is Settlement => !!s).map(s => s.ref),
  id: tx.id, apart: tx.apart_from ?? [], claim: tx.claimed_in?.ref ?? null,
})

// The kinds of document whose rows take Add line whether or not they print a total: they often have several lines.
const SEVERAL_LINES = new Set(['invoice', 'expense_claim', 'agent_statement'])

// Whether a person can add a line to the row's document: an invoice, a claim or an agent's statement, or any other
// document printing a total that its rows are checked against (a receipt split over accounts can come back a row
// short). A bank line is a transaction of its own, added with Add transaction.
export const takesLines = (tx: Transaction): boolean => {
  const type = tx.document_type ?? 'receipt'
  return !!tx.document_ref && type !== 'statement' && (SEVERAL_LINES.has(type) || tx.document_total != null)
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// 9 Sep 2026, as the API's messages write a date.
const longDate = (iso: string) => {
  const [year, month, day] = iso.split('-').map(Number)
  return `${day} ${MONTHS[month - 1]} ${year}`
}

const shortDate = (iso: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : 'no date'

const optionLabel = (option: Settlement[]) =>
  option.map(s => `${s.description} (${money(s.amount)}, ${shortDate(s.date)})`).join(' + ')

// A button under a row's description: clicking it makes the change, such as a bank line's link (null: match
// automatically) or the VAT of a receipt, to the row, or to another row (row: its id).
export interface RowAction { label: string; change: RowChange; row?: number }

// One status line under a row's description. `include` is set on a document that is not a transaction:
// the Include tick, and whether it is ticked.
export interface RowStatus { text: string; actions: RowAction[]; include?: boolean }

// What is still owed on a document, or how it was paid. Money in means they owe the business (a sale, a
// supplier's credit note, an agent's statement of rent collected); money out means the business owes them (a
// bill, a claim, a customer's credit note). An agent's statement has items both ways: its own direction decides.
function owedStatus(tx: Transaction): RowStatus | null {
  if (tx.owed == null) return null
  const owed = Number(tx.owed)
  const who = tx.agent ?? tx.counterparty ?? 'them'
  const text = !tx.paid_by?.length
    ? ((tx.document_direction ?? tx.direction) === 'in' ? `Unpaid, owed by ${who}` : `Unpaid, owed to ${who}`)
    : owed > 0 ? `Part paid: ${money(tx.owed)} still owed`
    : owed < 0 ? `Overpaid by ${money(String(-owed))}`
    : paidBy(tx.paid_by[tx.paid_by.length - 1])
  return { text, actions: [] }
}

const documentWord = (kind?: string | null) => (kind === 'receipt' || kind === 'invoice' ? kind : 'document')

// What paid a document: a bank line, or an agent's statement that took a bill it paid off the rent.
const paidBy = (by: Settlement) =>
  `Paid by ${by.kind === 'agent_statement' ? by.description : 'bank line'} on ${shortDate(by.date)}`

// The status lines under a row's description, with the person's choices: Include, Link, Unlink, Book VAT, and the
// date or the amount the row's other record shows (its claim line, receipt or card payment) when the two disagree.
export function rowStatus(tx: Transaction, find?: (id: number) => Transaction | undefined): RowStatus[] {
  const dated = tx.date_found ? [{ text: 'Which date is right?',
                                   actions: [{ label: `Use ${longDate(tx.date_found)}`, change: { date: tx.date_found } }] }]
    : []
  return [...statusLines(tx), ...dated, ...amountChoice(tx, find)]
}

// Where an amount came from, for a choice between two.
const SOURCES: Record<string, string> = { expense_claim: 'the claim', statement: 'the bank', receipt: 'the receipt',
                                          invoice: 'the invoice' }
const source = (tx: Transaction) => SOURCES[tx.document_type ?? 'receipt'] ?? 'the document'

// Which amount is right: each choice sets the record that differs to it, so the two pair and count once. When the
// other record asks too (a claim line and its receipt) either can change, the claim's amount first on both rows; a
// bank line's amount stands.
function amountChoice(tx: Transaction, find?: (id: number) => Transaction | undefined): RowStatus[] {
  if (!tx.amount_found) return []
  const partner = tx.issues.find(i => i.code === 'amount_conflict')?.related?.[0]
  const other = partner === undefined ? undefined : find?.(partner)
  if (!other) return [{ text: 'Which amount is right?', actions: [{ label: `Use ${money(tx.amount_found)}`,
                                                                    change: { gross: tx.amount_found } }] }]
  const theirs = { label: `${money(tx.amount_found)} (${source(other)})`, change: { gross: tx.amount_found } }
  const mine = { label: `${money(tx.gross)} (${source(tx)})`, change: { gross: tx.gross }, row: partner }
  const choices = other.amount_found ? (tx.document_type === 'expense_claim' ? [mine, theirs] : [theirs, mine]) : [theirs]
  return [{ text: 'Which amount is right?', actions: choices }]
}

// A choice between documents can also be declined: "None of these" makes it an ordinary bank line.
function statusLines(tx: Transaction): RowStatus[] {
  const type = tx.document_type ?? 'receipt'
  if (tx.recorded_by && type === 'expense_claim') {
    const word = documentWord(tx.recorded_by.kind)
    const from = `the ${word}: ${optionLabel([tx.recorded_by])}`
    return [{ text: tx.include ? `Booked as well as ${from}. Untick to book it from the ${word} only`
                               : `Booked from ${from}. Tick to book this line as well`,
              actions: [], include: !!tx.include }]
  }
  if (tx.claimed_in) {
    const on: RowStatus = { text: `On ${tx.claimed_in.description}: owed to the claimant`, actions: [] }
    // VAT the claim and the receipt's own prices agree on, left out because the receipt is not a VAT invoice.
    return tx.vat_found ? [on, { text: `VAT ${money(tx.vat_found)} not booked until you have the VAT invoice`,
                                 actions: [{ label: `Book VAT ${money(tx.vat_found)}`, change: { vat: tx.vat_found } }] }]
      : [on]
  }
  if (tx.copy_of) {
    const tick: RowStatus = {
      text: tx.include ? `Included as well as ${optionLabel([tx.copy_of])}`
        : `Same as ${optionLabel([tx.copy_of])}, not booked. Tick to include it as well`,
      actions: [], include: !!tx.include,
    }
    const owed = tx.include ? owedStatus(tx) : null
    return owed ? [tick, owed] : [tick]
  }
  if (type in NOT_TRANSACTIONS) {
    const tick: RowStatus = {
      text: tx.include ? 'Included as an invoice'
        : `Looks like ${NOT_TRANSACTIONS[type]}, not booked. Tick to include it as an invoice`,
      actions: [], include: !!tx.include,
    }
    const owed = tx.include ? owedStatus(tx) : null
    return owed ? [tick, owed] : [tick]
  }
  const kind = kindOf(tx)
  if (kind === 'document') {
    const owed = owedStatus(tx)
    // An item of an agent's statement also moved money: a bill the agent paid is paid by it.
    return [...(owed ? [owed] : []), ...(type === 'agent_statement' ? lineStatus(tx) : [])]
  }
  if (tx.recorded_by && tx.amount_found) {   // held while the amounts differ: the other record counts meanwhile
    return [{ text: `Not booked while the amounts differ: ${optionLabel([tx.recorded_by])} is booked meanwhile`, actions: [] }]
  }
  if (tx.recorded_by) {
    return [{ text: `Booked from the receipt: ${optionLabel([tx.recorded_by])}`,
              actions: [{ label: 'Unlink', change: { link: [] } }] }]
  }
  if (kind === 'bank') return lineStatus(tx)
  const card = type === 'receipt' ? tx.paid_by?.at(-1) : undefined
  return card ? [{ text: `Paid by card: bank line on ${shortDate(card.date)}`, actions: [] }] : []
}

// What a row that moved money pays, or could pay, with Link and Unlink.
function lineStatus(tx: Transaction): RowStatus[] {
  if (tx.pays?.length) return [{ text: `Pays: ${optionLabel(tx.pays)}`, actions: [{ label: 'Unlink', change: { link: [] } }] }]
  if (tx.candidates?.length) {
    const choosing = tx.issues.some(i => i.code === 'choose_payment')
    return [{
      text: choosing ? 'Could pay:' : 'May pay:',
      actions: [
        ...tx.candidates.map(option => ({ label: `Link ${optionLabel(option)}`, change: { link: option.map(s => s.ref) } })),
        { label: 'None of these', change: { link: [] } },
      ],
    }]
  }
  if (tx.link && !tx.link.length) {
    return [{ text: 'Not matched to a document', actions: [{ label: 'Match automatically', change: { link: null } }] }]
  }
  return []
}

// What each kind of issue is called where the table lists it; the message says the rest.
const ISSUE_TITLES: Record<string, string> = {
  total_mismatch: "Total doesn't add up", possible_duplicate: 'Possible duplicate', duplicate_document: 'Copy of a document',
  choose_payment: 'Choose what it pays', possible_payment: 'May pay a document', part_payment: 'Part payment',
  overpayment: 'Overpaid', stale_link: 'Link no longer found', mixed_link: "Links can't be combined",
  claim_vat: 'VAT not on the receipt', vat_worked_out: 'VAT worked out', not_vat_invoice: 'Not a VAT invoice',
  vat_arithmetic: 'Impossible VAT', vat_rate_mismatch: 'Unusual VAT',
  vat_estimated: 'VAT estimated', vat_not_applicable: 'VAT ignored', vat_blocked: "VAT can't be reclaimed",
  date_conflict: 'Which date?', file_date: 'Date to check', date_from_claim: 'Date from the claim',
  date_from_bank: 'Date from the bank', booked_twice: 'Booked twice', amount_conflict: 'Which amount?',
  account_not_recognised: 'Account to check', unknown_account: 'Unknown account', same_account: 'Same account twice',
  non_gbp_currency: 'Not in pounds', date_missing: 'No date', date_out_of_period: 'Outside the period',
  unusual_direction: 'Unusual direction', director_loan: 'Owner account', not_booked: 'Not booked',
  statement_gap: "Balance doesn't follow", statement_total: "Statement doesn't add up", mixed_items: 'Mixed items',
  direction_conflict: 'Direction changed',
}

export const issueTitle = (code: string) => ISSUE_TITLES[code] ?? 'Check this'

// The Check column's hover: the names of the row's issues, once each. The Description column has the messages.
export const checkHover = (issues: Issue[]) =>
  issues.length ? [...new Set(issues.map(i => issueTitle(i.code)))].join(', ') : 'No issues'

// The Account column: the account's name, never its code; for a bank line that pays a document, the account it
// settles. An account not in the chart has no name.
export const accountName = (tx: Transaction): string =>
  (tx.paid_against ? tx.paid_against_name : tx.account_name) || 'Unknown account'

// The title as the start of the message: a sentence, unless it is a question already.
export const issueHeading = (code: string) => {
  const title = issueTitle(code)
  return /[?!.]$/.test(title) ? title : `${title}.`
}

// The issues about this row and others, which offer Show both (Show its lines, for a document's total): the rows side
// by side, without searching the table.
const ABOUT_ANOTHER_ROW = new Set(['possible_duplicate', 'date_conflict', 'amount_conflict', 'booked_twice',
                                   'total_mismatch'])
export const aboutAnotherRow = (code: string) => ABOUT_ANOTHER_ROW.has(code)
export const showLabel = (code: string) => (code === 'total_mismatch' ? 'Show its lines' : 'Show both')

// The issues where two records may be one, which a person can answer Not the same.
const MAY_BE_ONE = new Set(['possible_duplicate', 'date_conflict', 'amount_conflict'])
export const canBeApart = (code: string) => MAY_BE_ONE.has(code)

// Not the same: the row is kept apart from the rows the issue was about, as well as any it already was.
export const apartChange = (tx: Transaction, related: number[]): RowChange =>
  ({ apart_from: [...new Set([...(tx.apart_from ?? []), ...related])] })

// The status line of a row a person kept apart from others, with Undo; none when those rows are gone.
export function apartStatus(tx: Transaction, describe: (id: number) => string | undefined): RowStatus | null {
  const names = (tx.apart_from ?? []).map(describe).filter((name): name is string => !!name)
  return names.length ? { text: `Not the same as ${names.map(n => `"${n}"`).join(', ')} (you said)`,
                          actions: [{ label: 'Undo', change: { apart_from: [] } }] } : null
}

export interface ReviewItem { code: string; title: string; severity: 'warning' | 'error'; rows: number }

// What needs a person, by kind of issue: how many rows have each warning or error (notes are left out). Errors first.
export function reviewSummary(issuesByRow: Issue[][]): ReviewItem[] {
  const found = new Map<string, ReviewItem>()
  for (const issues of issuesByRow) {
    for (const code of new Set(issues.filter(i => i.severity !== 'info').map(i => i.code))) {
      const severity = issues.some(i => i.code === code && i.severity === 'error') ? 'error' : 'warning'
      const item = found.get(code) ?? { code, title: issueTitle(code), severity, rows: 0 }
      item.rows += 1
      if (severity === 'error') item.severity = 'error'
      found.set(code, item)
    }
  }
  return [...found.values()].sort((a, b) => Number(b.severity === 'error') - Number(a.severity === 'error')
                                           || b.rows - a.rows || a.title.localeCompare(b.title))
}

export interface TotalRow {
  key: string
  label: string
  count: number
  gross: string | null
  vat: string | null
  net: string | null
  stillOwed?: string     // documents only: what is still owed on them
}

// Totals by how rows are booked, in whole pennies so they don't drift: money that moved through the
// bank, and documents (bills, claims, sales invoices, credit notes) with what is still owed on them. An
// unpaid bill is not money out, so the two are kept apart; rows not booked are left out. A row with an
// error (impossible VAT) has no VAT or net, so its group's VAT and net totals are unknown.
export function totalsOf(txs: Transaction[]): TotalRow[] {
  const sum = (values: (string | null)[]) => values.some(v => v == null) ? null
    : (values.reduce((pennies, v) => pennies + Math.round(Number(v) * 100), 0) / 100).toFixed(2)
  const moved = (tx: Transaction) => ['bank', 'other'].includes(kindOf(tx))
  const groups = [
    { key: 'bank-out', label: 'Paid out (bank)', keep: (tx: Transaction) => moved(tx) && tx.direction === 'out' },
    { key: 'bank-in', label: 'Received (bank)', keep: (tx: Transaction) => moved(tx) && tx.direction === 'in' },
    { key: 'documents-out', label: 'Documents, money out', keep: (tx: Transaction) => kindOf(tx) === 'document' && tx.direction === 'out' },
    { key: 'documents-in', label: 'Documents, money in', keep: (tx: Transaction) => kindOf(tx) === 'document' && tx.direction === 'in' },
  ]
  return groups.flatMap(({ key, label, keep }) => {
    const rows = txs.filter(keep)
    if (!rows.length) return []
    const total: TotalRow = { key, label, count: rows.length, gross: sum(rows.map(tx => tx.gross)),
                              vat: sum(rows.map(tx => tx.vat_posted)), net: sum(rows.map(tx => tx.net)) }
    if (key.startsWith('documents')) {
      // What is still owed is carried by every row of a document, so it is counted once per document, on the side
      // it is owed: an agent's statement has rows both ways.
      const side = key === 'documents-in' ? 'in' : 'out'
      const owed = new Map(txs.filter(tx => kindOf(tx) === 'document' && (tx.document_direction ?? tx.direction) === side)
        .map((tx, i) => [tx.document_ref ?? `row-${i}`, Math.max(0, Number(tx.owed ?? 0))]))
      total.stillOwed = ([...owed.values()].reduce((pennies, v) => pennies + Math.round(v * 100), 0) / 100).toFixed(2)
    }
    return [total]
  })
}
