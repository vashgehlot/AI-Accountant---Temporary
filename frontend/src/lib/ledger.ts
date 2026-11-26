// What the table shows for each row and in its totals: how a row is booked, the status line under its
// description with the choices it offers a person, and the totals. Pure functions, tested in ledger.test.ts.
import type { Issue, Settlement, Transaction } from './api'
import type { RowChange } from './clients'
import { DOCUMENT_TYPES } from './clientRules.ts'

const fmt = (n: number) =>
  n === 0
    ? ''
    : `£${Math.abs(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// Money as the table shows it: £1,234.50, or a dash when unknown.
export const money = (value: string | null | undefined) => (value == null ? '—' : fmt(Number(value)) || '£0.00')

export const NOT_TRANSACTIONS: Record<string, string> = {
  quote: 'a quote', pro_forma: 'a pro forma invoice', purchase_order: 'a purchase order',
  remittance_advice: 'a remittance advice', supplier_statement: "a supplier's statement of account",
  finance_agreement: 'a finance or loan agreement',
  other: 'a document that is not a transaction',
}

export type RowKind = 'document' | 'bank' | 'other' | 'not booked'

// How a row is booked: a document holding what is owed, a bank line, anything else paid when it
// happened, or not booked at all (a quote or the like, a copy of a document, or a claim line its receipt books,
// until a person ticks Include; a card payment, which its receipt books).
export const kindOf = (tx: Transaction): RowKind => {
  const type = tx.document_type ?? 'receipt'
  if (!tx.include && (tx.copy_of || tx.recorded_by || tx.left_off_claim)) return 'not booked'
  if (tx.claimed_in) return 'document'   // a receipt on an expense claim is owed to the claimant, not paid by the business
  if (type in NOT_TRANSACTIONS) return tx.include ? 'document' : 'not booked'
  if (type === 'invoice' || type === 'expense_claim' || type === 'agent_statement') return 'document'
  return type === 'statement' ? 'bank' : 'other'
}

// A row a decision left out of the books or replaced with a split: the table still lists it, crossed out.
export const leftOut = (tx: Transaction) => !!(tx.excluded || tx.superseded_by)

// What a row left out of the books says under its description: who took it out.
export const leftOutLabel = (tx: Transaction): 'Replaced' | 'Removed by you' | 'Left out' =>
  tx.superseded_by ? 'Replaced' : tx.removed ? 'Removed by you' : 'Left out'

// Whether Remove deletes the row for good: only a row typed in by hand. A row read from a file is set aside, stays
// listed, and can be put back.
export const removedForGood = (row: { upload_id: number }, uploads: { id: number; kind: string }[]): boolean =>
  uploads.some(u => u.id === row.upload_id && u.kind === 'manual')

// A row's own issues: those about the row, not about its whole document (documentProblems lists those).
export const rowIssues = (tx: Transaction): Issue[] => tx.issues.filter(i => i.about !== 'document')

// A problem with a whole document (its lines don't reach its total, and no one line explains why): the row that
// carries it (the document's first), the issue, and every line of the document that is in the books.
export interface DocumentProblem<Row extends Transaction & { id: number }> { row: Row; issue: Issue; lines: number[] }
export function documentProblems<Row extends Transaction & { id: number }>(rows: Row[]): DocumentProblem<Row>[] {
  const inBooks = rows.filter(r => !leftOut(r))
  return inBooks.flatMap(row => row.issues.filter(i => i.about === 'document' && i.severity !== 'info').map(issue => ({
    row, issue, lines: inBooks.filter(r => r.id === row.id || (!!row.document_ref && r.document_ref === row.document_ref)).map(r => r.id),
  })))
}

// The rows a link to the Transactions page opens on, the asked-for one first: beside the rows its issues name, or,
// for a link to its document's problem, beside every line of that document. None when the row is not in the year.
export function linkedRows<Row extends Transaction & { id: number }>(rows: Row[], id: number, document: boolean): number[] | undefined {
  const asked = rows.find(r => r.id === id)
  if (!asked) return undefined
  if (document) return documentProblems(rows).find(d => d.row.id === id)?.lines ?? [id]
  return [id, ...asked.issues.flatMap(i => i.related ?? [])]
}

// Whether a row needs a person: it has a warning or an error (its own, or those the page adds, such as a possible
// duplicate), and it is in the books. What is wrong with a row left out no longer matters; the agent skips it too.
export const needsReview = (tx: Transaction, issues: Issue[] = tx.issues) =>
  !leftOut(tx) && issues.some(i => i.severity !== 'info')

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
export const longDate = (iso: string) => {
  const [year, month, day] = iso.split('-').map(Number)
  return `${day} ${MONTHS[month - 1]} ${year}`
}

const shortDate = (iso: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : 'no date'

const optionLabel = (option: Settlement[]) =>
  option.map(s => `${s.description} (${money(s.amount)}${s.date ? `, ${shortDate(s.date)}` : ''})`).join(' + ')

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
  return [...statusLines(tx), ...dated, ...amountChoice(tx, find), ...bookedWithout(tx)]
}

// A purchase a person booked without the receipt or invoice the rules want: why, and a way to hold it in Suspense for
// the document again. Only while the rules would otherwise hold it (the API says so with booked_without_document).
function bookedWithout(tx: Transaction): RowStatus[] {
  if (!tx.without_document || !tx.issues.some(i => i.code === 'booked_without_document')) return []
  return [{ text: `Booked without a receipt: ${tx.without_document}. No VAT reclaimed`,
            actions: [{ label: 'Hold for the receipt instead', change: { without_document: null } }] }]
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
    const several = (tx.recorded_by_refs?.length ?? 0) > 1   // several receipts of one document: a TfL statement's days
    const word = several ? 'receipts' : documentWord(tx.recorded_by.kind)
    const from = `${several ? tx.recorded_by_refs!.length : 'the'} ${word}: ${optionLabel([tx.recorded_by])}`
    return [{ text: tx.include ? `Booked as well as ${from}. Untick to book it from the ${word} only`
                               : `Booked from ${from}. Tick to book this line as well`,
              actions: [], include: !!tx.include }]
  }
  if (tx.left_off_claim) {   // a charge on the document the claim leaves out: the claimant paid it
    return [{ text: tx.include ? `Included, though not on ${tx.left_off_claim.description}`
                               : `Not on ${tx.left_off_claim.description}, not booked. Tick to include it`,
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
  return card ? [{ text: `Paid from the bank: line on ${shortDate(card.date)}`, actions: [] }] : []
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
  total_mismatch: "Total doesn't add up", total_accepted: 'Total left as it is', possible_duplicate: 'Possible duplicate', duplicate_document: 'Copy of a document',
  choose_payment: 'Choose what it pays', paid_oldest: 'Paid the oldest', converted_currency: 'Converted to pounds', credited: 'Credit note applied', hmrc_reference: 'Coded by its HMRC reference', employment_allowance: 'Employment Allowance', bad_debt_recovered: 'Bad debt recovered', vat_half_blocked: 'Half the VAT reclaimed', under_capitalisation: 'Under the capitalisation threshold', paid_before_invoice: 'Paid before the invoice', claim_paid: 'Pays an expense claim', possible_payment: 'May pay a document', open_document: 'May pay an open invoice', part_payment: 'Part payment',
  overpayment: 'Overpaid', stale_link: 'Link no longer found', mixed_link: "Links can't be combined",
  claim_vat: 'VAT not on the receipt', vat_worked_out: 'VAT worked out', not_vat_invoice: 'Not a VAT invoice',
  vat_arithmetic: 'Impossible VAT', vat_rate_mismatch: 'Unusual VAT',
  vat_estimated: 'VAT estimated', vat_not_applicable: 'VAT ignored', vat_blocked: "VAT can't be reclaimed",
  date_conflict: 'Which date?', file_date: 'Date to check', date_from_claim: 'Date from the claim',
  date_from_bank: 'Date from the bank', booked_twice: 'Booked twice', amount_conflict: 'Which amount?',
  account_not_recognised: 'Account to check', account_unclear: 'Account to check', unknown_account: 'Unknown account', same_account: 'Same account twice',
  non_gbp_currency: 'Not in pounds', date_missing: 'No date', date_out_of_period: 'Outside the period',
  unusual_direction: 'Unusual direction', director_loan: 'Owner account', not_booked: 'Not booked', before_first_year: 'Before the first year',
  statement_gap: "Balance doesn't follow", statement_total: "Statement doesn't add up", mixed_items: 'Mixed items',
  direction_conflict: 'Direction changed', no_payroll: 'No payroll report', wages_from_bank: 'Wages from the bank',
  payroll_owed_to: 'Check the payroll line', sale_without_vat: 'Sale with no VAT', transfer: 'Transfer between accounts',
  no_vat_number: 'No VAT number on the invoice', vat_over_rate: 'VAT above 20%', reverse_charge: 'Reverse charge',
  before_vat_registration: 'Before VAT registration', small_asset: 'Small for an asset', meal_check: 'Who was it for?',
  sundry_check: 'Sundry: what was it for?', claim_note: 'Coded by the claim', account_fact: 'Which account?',
  account_choice: 'Another account?', left_small: 'Left: under the trivial level', left_unset: 'Left: materiality not set', meal_decided: 'Who was there: settled', small_items_add_up: 'Small items add up',
  addressed_to: 'Addressed to someone else', refund_of_overpayment: 'Refund of an overpayment',
  future_date: 'Dated in a later year', journal_note: 'Journal', prepayment: 'Paid ahead?', reversed: 'Reversed',
  not_on_statement: 'Not on the statement', till_takings: 'Till takings',
  unusual_account: "Not this supplier's usual account", asset_check: 'Checked for equipment', should_be_asset: 'Equipment?', whose_account: 'Whose account?',
  vat_not_booked: 'VAT not booked', needs_document: 'Needs its document', booked_without_document: 'Booked without a receipt', claimed_less: 'Claimed less than its bill', total_worked_out: 'Total not printed',
  card_credit: 'Money in on a card', vat_unclaimed: 'VAT not reclaimed', on_account: 'Payment on account',
  vat_confirmed: 'VAT reclaimed on your say', vat_implied: 'VAT worked out', document_wanted: 'Invoice needed', hotel_vat: 'Invoice needed',
  payroll_person: 'Check this person\'s pay', meal_recoded: 'Booked to Subsistence', payroll_total: 'Payroll doesn\'t add up', cis_deducted: 'CIS deducted', payout_report: 'Payout report needed', personal: 'Looks personal', for_the_trade: 'Kept for the business', subtotal_only: 'Total not printed',
  not_claimed: 'Not claimed', claim_receipts_unclear: "Can't tell which charges",
}

export const issueTitle = (code: string) => ISSUE_TITLES[code] ?? 'Check this'

// The Check column's hover: the names of the row's issues, once each. The Description column has the messages.
export const checkHover = (issues: Issue[]) =>
  issues.length ? [...new Set(issues.map(i => issueTitle(i.code)))].join(', ') : 'No issues'

// The Account column: the account's name, never its code; for a bank line that pays a document, the account it
// settles. An account not in the chart has no name.
// The account a row is on in the books now: a bank line its receipt or the other side of a transfer books posts
// nothing itself; a row waiting for its document is in Suspense until it comes, then on its own account.
export function accountName(tx: Transaction): string {
  if (tx.document_type === 'journal') {
    return `Dr ${tx.account_name || tx.account_code}, Cr ${tx.contra_account_name || tx.contra_account_code || 'unknown'}`
  }
  if (tx.recorded_by) return 'Booked from its document'
  const own = (tx.paid_against ? tx.paid_against_name : tx.account_name) || 'Unknown account'
  const held = tx.issues?.some(i => i.code === 'needs_document') && tx.account_code !== '9998'
  return held ? `Suspense, then ${own}` : own
}

// The title as the start of the message: a sentence, unless it is a question already.
export const issueHeading = (code: string) => {
  const title = issueTitle(code)
  return /[?!.]$/.test(title) ? title : `${title}.`
}

// The issues about this row and others, which offer Show both (Show its lines, for a document's total): the rows side
// by side, without searching the table.
const ABOUT_ANOTHER_ROW = new Set(['possible_duplicate', 'date_conflict', 'amount_conflict', 'booked_twice',
                                   'total_mismatch', 'claim_receipts_unclear'])
export const aboutAnotherRow = (code: string) => ABOUT_ANOTHER_ROW.has(code)
export const showLabel = (code: string) => (code === 'total_mismatch' ? 'Show its lines' : 'Show both')

// The issues where two records may be one, which a person can answer Not the same.
const MAY_BE_ONE = new Set(['possible_duplicate', 'date_conflict', 'amount_conflict'])
export const canBeApart = (code: string) => MAY_BE_ONE.has(code)

// Warnings that are a matter of judgement, which a person who has looked can answer It's fine (checks.ACCEPTABLE).
const ACCEPTABLE = new Set(['no_vat_number', 'vat_over_rate', 'small_asset', 'meal_check', 'sundry_check', 'account_fact',
                            'account_choice', 'small_items_add_up', 'addressed_to', 'future_date',
                            'file_date', 'unusual_account', 'asset_check', 'should_be_asset', 'whose_account', 'claim_vat', 'document_wanted',
                            'hotel_vat'])
export const canBeAccepted = (code: string) => ACCEPTABLE.has(code)
// What accepting a warning is called on its button: the row stays booked as it is, and stops asking.
export const acceptLabel = (code: string) =>
  (code === 'document_wanted' || code === 'hotel_vat' ? "It's fine without one" : "It's fine")

// A way to fix an issue, offered on the issue itself: a change made at once, a list to choose from there on the
// row, the Edit dialog, or the Documents page for a file that is missing.
export interface IssueFix {
  label: string
  change?: RowChange       // made at once
  choose?: 'account'       // the client's accounts, to pick one from
  edit?: boolean           // opens Edit
  documents?: boolean      // goes to Documents, to add the file
}

const SUSPENSE = '9998'
const ACCOUNT_ISSUES = new Set(['account_unclear', 'account_not_recognised', 'unknown_account', 'same_account'])
const DATE_ISSUES = new Set(['date_missing', 'date_out_of_period', 'before_first_year'])
const VAT_ISSUES = new Set(['vat_arithmetic', 'vat_rate_mismatch', 'vat_estimated', 'sale_without_vat', 'vat_not_booked'])
const DOCUMENT_ISSUES = new Set(['needs_document', 'document_wanted', 'no_payroll', 'payout_report'])

// The line of an expense claim that the row's receipt or invoice backs, among the year's rows: what the claimant
// said it was (its account, its VAT), which a fix can take.
export const claimLineOf = (tx: Transaction, rows: Transaction[]): Transaction | undefined =>
  tx.claimed_in && tx.document_ref
    ? rows.find(r => r.document_type === 'expense_claim' && r.document_ref === tx.claimed_in!.ref
                     && (r.recorded_by?.ref === tx.document_ref || !!r.recorded_by_refs?.includes(tx.document_ref!)))
    : undefined

// How a person can fix a warning or an error from where it is listed (a note needs no fix). claimLine: claimLineOf.
// An issue with controls of its own elsewhere on the row (Link, Show both, Not the same, It's fine) offers none here.
export function issueFixes(tx: Transaction, issue: Issue, claimLine?: Transaction): IssueFix[] {
  // The note on VAT reclaimed on a person's say is where they take that back.
  if (issue.code === 'vat_confirmed') return [{ label: "Don't reclaim it", change: { vat_confirmed: false } }]
  // VAT worked out of the amount because the document shows a VAT number or says VAT: a person who knows it
  // carries none says so, or enters what it does carry.
  if (issue.code === 'vat_implied') return [{ label: 'No VAT on it', change: { vat: '0.00' } }, { label: 'Enter the VAT', edit: true }]
  // A total a person said to leave as it is: the note is where they take that back.
  if (issue.code === 'total_accepted') return [{ label: 'Undo', change: { total_accepted: null } }]
  if (issue.severity === 'info') return []
  const code = issue.code
  // A total that doesn't add up on purpose (a line removed long ago, a total printed wrong): the person says so.
  if (code === 'total_mismatch') return issue.difference ? [{ label: 'Leave it as it is', change: { total_accepted: issue.difference } }] : []
  if (ACCOUNT_ISSUES.has(code)) {
    const theirs = claimLine?.account_code && claimLine.account_code !== SUSPENSE && claimLine.account_code !== tx.account_code
      ? [{ label: `Use ${claimLine.account_name || claimLine.account_code}, as the claim has it`,
           change: { account_code: claimLine.account_code } }]
      : []
    return [...theirs, { label: 'Choose the account', choose: 'account' }]
  }
  if (code === 'claim_vat') {
    // Booked as the claim shows it already: the way out is to say it carries none.
    if (tx.vat_from_claim) return [{ label: 'No VAT on it', change: { vat: '0.00' } }]
    return claimLine?.vat && Number(claimLine.vat) > 0
      ? [{ label: `Book VAT ${money(claimLine.vat)}, as claimed`, change: { vat: claimLine.vat } }]
      : [{ label: 'Enter the VAT', edit: true }]
  }
  // VAT read on a row whose account takes none: on Suspense it goes once the account is chosen.
  if (code === 'vat_not_applicable') return tx.account_code === SUSPENSE ? [] : [{ label: 'Remove the VAT', change: { vat: null } }]
  if (code === 'non_gbp_currency') return [{ label: 'Enter it in pounds', edit: true }]
  if (DATE_ISSUES.has(code)) return [{ label: 'Set the date', edit: true }]
  if (VAT_ISSUES.has(code)) return [{ label: 'Correct the VAT', edit: true }]
  // A UK hotel stay booked with its 20% VAT before the property's VAT invoice is in: add the invoice, or say it
  // carries none (a stay abroad, or a host not registered for VAT).
  if (code === 'hotel_vat') return [{ label: 'Add the document', documents: true }, { label: 'No VAT on it', change: { vat: '0.00' } }]
  if (DOCUMENT_ISSUES.has(code)) {
    // A row held for its VAT invoice with VAT on it: the person can vouch for the VAT, which books the row.
    // or say it carries none, which books it whole.
    const reclaim: IssueFix[] = code === 'needs_document' && tx.vat_not_reclaimed
      ? [{ label: `Reclaim VAT ${money(tx.vat_not_reclaimed)} and book it`, change: { vat_confirmed: true } },
         { label: 'No VAT on it', change: { vat: '0.00' } }] : []
    return [...reclaim, { label: 'Add the document', documents: true }]
  }
  return []
}

// What to ask the AI about an issue, from the row: the chat opens on the client with this as its first message.
export const askAbout = (tx: Transaction, issue: Issue) =>
  `Help me fix this: "${tx.description}"${tx.date ? `, ${longDate(tx.date)}` : ''}, ${money(tx.gross)}. `
  + `${issueHeading(issue.code)} ${issue.message} Tell me the options, and make the change when I say which.`
export const acceptChange = (tx: Transaction, code: string): RowChange =>
  ({ accepted: [...new Set([...(tx.accepted ?? []), code])] })

// Not the same: the row is kept apart from the rows the issue was about, as well as any it already was.
export const apartChange = (tx: Transaction, related: number[]): RowChange =>
  ({ apart_from: [...new Set([...(tx.apart_from ?? []), ...related])] })

// The status line of a row a person kept apart from others, with Undo; none when those rows are gone.
export function apartStatus(tx: Transaction, describe: (id: number) => string | undefined): RowStatus | null {
  const names = (tx.apart_from ?? []).map(describe).filter((name): name is string => !!name)
  return names.length ? { text: `Not the same as ${names.map(n => `"${n}"`).join(', ')} (you said)`,
                          actions: [{ label: 'Undo', change: { apart_from: [] } }] } : null
}

// The VAT and the net the books hold for a row. VAT the document rules don't reclaim (a row held in Suspense for its
// VAT invoice, a receipt that isn't a VAT invoice) stays in the amount: none is booked, and the net is the whole
// amount. So the table and its totals agree with the trial balance.
const pounds = (pennies: number) => (pennies / 100).toFixed(2)
const pennies = (value: string) => Math.round(Number(value) * 100)
export const vatBooked = (tx: Transaction): string | null => (tx.vat_not_reclaimed ? '0.00' : tx.vat_posted)
export const netBooked = (tx: Transaction): string | null =>
  tx.vat_not_reclaimed && tx.net != null ? pounds(pennies(tx.net) + pennies(tx.vat_not_reclaimed)) : tx.net

// ─── Filtering the table ─────────────────────────────────────────────────────

// What the table can be narrowed by, all at once: words, account, kind of document, direction, dates, amounts and
// what state the row is in. An empty field doesn't narrow.
export interface RowFilters {
  text: string        // words found in the description, who was paid, the file, the document number or the account
  account: string     // an account code
  type: string        // a document type
  direction: '' | 'in' | 'out'
  from: string        // dates, YYYY-MM-DD, both included
  to: string
  min: string         // amounts in pounds, both included
  max: string
  status: '' | 'review' | 'edited' | 'vat' | 'no_vat' | 'not_booked'
}
export const NO_FILTERS: RowFilters = { text: '', account: '', type: '', direction: '', from: '', to: '', min: '', max: '', status: '' }

// How many fields narrow the table.
export const filtersSet = (f: RowFilters): number => Object.values(f).filter(v => v.trim() !== '').length

// Whether a row passes every field that is set. Every word typed must be found somewhere on the row; a row with no
// date fails a date limit; an amount that isn't a number doesn't narrow.
export function matchesFilters(tx: Transaction & { edited?: boolean }, f: RowFilters, fileName = ''): boolean {
  const words = f.text.toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length) {
    const on = [tx.description, tx.counterparty, fileName, tx.document_number, tx.account_name, tx.account_code, tx.gross]
      .filter(Boolean).join(' ').toLowerCase()
    if (!words.every(w => on.includes(w))) return false
  }
  if (f.account && tx.account_code !== f.account) return false
  if (f.type && (tx.document_type ?? 'receipt') !== f.type) return false
  if (f.direction && tx.direction !== f.direction) return false
  if ((f.from || f.to) && !tx.date) return false
  if (f.from && tx.date! < f.from) return false
  if (f.to && tx.date! > f.to) return false
  const amount = Number(tx.gross)
  const min = f.min.trim() === '' ? NaN : Number(f.min)
  const max = f.max.trim() === '' ? NaN : Number(f.max)
  if (!Number.isNaN(min) && amount < min) return false
  if (!Number.isNaN(max) && amount > max) return false
  if (f.status === 'review' && !needsReview(tx)) return false
  if (f.status === 'edited' && !tx.edited) return false
  if (f.status === 'vat' && !(Number(vatBooked(tx) ?? 0) > 0)) return false
  if (f.status === 'no_vat' && Number(vatBooked(tx) ?? 0) > 0) return false
  if (f.status === 'not_booked' && kindOf(tx) !== 'not booked' && !leftOut(tx)) return false
  return true
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
// unpaid bill is not money out, so the two are kept apart; rows not booked, and rows left out of the books, are
// left out. A row with an error (impossible VAT) has no VAT or net, so its group's VAT and net totals are unknown.
export function totalsOf(all: Transaction[]): TotalRow[] {
  const txs = all.filter(tx => !leftOut(tx))
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
                              vat: sum(rows.map(vatBooked)), net: sum(rows.map(netBooked)) }
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

/** The note for the Overview when the posted ledger is behind the changes; null when it is up to date or not yet known. */
export function postedLedgerNote(unposted: number | null): string | null {
  if (!unposted) return null
  return `Not up to date: ${unposted} ${unposted === 1 ? 'change' : 'changes'} not posted. See Trial balance.`
}

// A client's materiality for a year, as GET .../materiality gives it (ledgersync/materiality.py); null: no figures.
export interface Levels {
  overall: string
  working: string
  trivial: string
  benchmark: 'profit' | 'costs' | 'firm'
  figure?: string | null
  basis: string
}


const gbp = (amount: string) => `£${Number(amount).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// The line above the to-do list: how much is too little to ask about, and what it was worked out from.
export const levelsLine = (levels: Levels | null) =>
  levels ? `Materiality ${gbp(levels.overall)} (${levels.basis}) · items under ${gbp(levels.trivial)} left as coded`
         : "Materiality not set: no sales booked and no earlier year to work it out from. Set it in the client's "
           + 'details; until then, questions where either account is right wait. Questions that change the tax are asked now.'

// How many rows the Transactions table draws at a time: a year of 1,351 rows drawn at once is slow to show.
export const ROWS_PER_PAGE = 200

// The first `limit` of the rows the table lists, and how many more it has.
export const pageOf = <T>(rows: T[], limit: number): { shown: T[]; more: number } =>
  ({ shown: rows.slice(0, limit), more: Math.max(0, rows.length - limit) })

// How many rows the table must list to show this one: the pages up to it, never fewer than it lists now. A row the
// table doesn't list (filtered out) changes nothing.
export function pageReaching(ids: number[], id: number | null, limit: number): number {
  const at = id === null ? -1 : ids.indexOf(id)
  return at < 0 ? limit : Math.max(limit, Math.ceil((at + 1) / ROWS_PER_PAGE) * ROWS_PER_PAGE)
}

// The row the panel shows once these rows are shown together: the open one if it is among them, else the first.
export const keepSelected = (selected: number | null, ids: number[]): number | null =>
  selected !== null && ids.includes(selected) ? selected : ids[0] ?? null

// The "Needs review" choice: the flagged rows, and apart from them the documents with a problem of their own.
export function needsReviewLabel(rows: number, documents: number): string {
  const n = (count: number, one: string) => `${count.toLocaleString('en-GB')} ${one}${count === 1 ? '' : 's'}`
  return `Needs review · ${[rows ? n(rows, 'row') : '', documents ? n(documents, 'document') : ''].filter(Boolean).join(', ')}`
}

// ─── The compact table ───────────────────────────────────────────────────────

// 01 Apr 23: a date that never wraps in the table's first column.
export const tableDate = (iso: string | null | undefined): string => {
  if (!iso) return '—'
  const [year, month, day] = iso.split('-').map(Number)
  return `${String(day).padStart(2, '0')} ${MONTHS[month - 1]} ${String(year).slice(-2)}`
}

// The amount as the table shows it: +4,800.00 for money in, −504.00 (a minus sign) for money out; a journal moves
// money between accounts, so it has no sign.
export function signedAmount(tx: Transaction): { text: string; tone: 'in' | 'out' | 'plain' } {
  const figure = Math.abs(Number(tx.gross)).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (tx.document_type === 'journal') return { text: figure, tone: 'plain' }
  return tx.direction === 'in' ? { text: `+${figure}`, tone: 'in' } : { text: `−${figure}`, tone: 'out' }
}

// The line under a row's description: its worst warning or error, with +N for the rest (a document's problem counts
// as one of them); else its kind of document and its first status ("Invoice · paid 3 Oct"); "left out" for a row
// out of the books, which is never flagged.
export function rowHeadline(tx: Transaction, issues: Issue[], documentIssue?: Issue | null, why?: string | null):
    { text: string; severity: 'error' | 'warning' | 'info' | null } {
  if (leftOut(tx)) return { text: leftOutLabel(tx).toLowerCase() + (why ? ` · ${why}` : ''), severity: null }
  const flags = [...issues, ...(documentIssue ? [documentIssue] : [])].filter(i => i.severity !== 'info')
  if (flags.length) {
    const worst = flags.find(i => i.severity === 'error') ?? flags[0]
    return { text: issueTitle(worst.code) + (flags.length > 1 ? ` · +${flags.length - 1}` : ''), severity: worst.severity }
  }
  const type = DOCUMENT_TYPES[tx.document_type ?? 'receipt'] ?? 'Document'
  const first = rowStatus(tx)[0]?.text.replace(/^Paid by .* on (.+)$/, 'paid $1')
  return { text: first ? `${type} · ${first}` : type, severity: null }
}

// A status's choices: the first few links as buttons and the rest for a picker (a payout can be any of 45
// statements); every other choice, "None of these" among them, stays a button after the links.
export function capActions(actions: RowAction[], limit = 3): { shown: RowAction[]; rest: RowAction[] } {
  const isLink = (a: RowAction) => !!a.change.link?.length
  const links = actions.filter(isLink)
  return { shown: [...links.slice(0, limit), ...actions.filter(a => !isLink(a))], rest: links.slice(limit) }
}

const STATE_NAMES: Record<string, string> = { review: 'To review', edited: 'Edited', vat: 'With VAT', no_vat: 'No VAT',
                                              not_booked: 'Not booked' }

// The filters set, one chip each, as the bar lists them under itself; the two dates are one chip, and so are the two
// amounts. Each chip's field is what its × clears.
export function filterChips(f: RowFilters, names: { account: (code: string) => string; type: (t: string) => string }):
    { field: keyof RowFilters | 'dates' | 'amounts'; label: string }[] {
  const chips: { field: keyof RowFilters | 'dates' | 'amounts'; label: string }[] = []
  const range = (low: string, high: string, show: (v: string) => string, from: string, upTo: string) =>
    low && high ? `${show(low)} – ${show(high)}` : low ? `${from} ${show(low)}` : `${upTo} ${show(high)}`
  if (f.text.trim()) chips.push({ field: 'text', label: `“${f.text.trim()}”` })
  if (f.account) chips.push({ field: 'account', label: names.account(f.account) })
  if (f.type) chips.push({ field: 'type', label: names.type(f.type) })
  if (f.direction) chips.push({ field: 'direction', label: f.direction === 'in' ? 'Money in' : 'Money out' })
  if (f.status) chips.push({ field: 'status', label: STATE_NAMES[f.status] ?? f.status })
  if (f.from || f.to) chips.push({ field: 'dates', label: range(f.from, f.to, tableDate, 'From', 'Until') })
  if (f.min.trim() || f.max.trim()) {
    chips.push({ field: 'amounts', label: range(f.min.trim(), f.max.trim(), v => money(v), 'From', 'Up to') })
  }
  return chips
}
