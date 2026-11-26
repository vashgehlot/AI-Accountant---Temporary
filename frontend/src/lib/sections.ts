// What the Bank and Invoices sections say and show, kept apart from the screens so node --test can run them.
import type { TrialBalanceResult } from './api'
import type { AccountChoice, BankCheck, Client, InvoiceSummary, Ledger, OpeningBalances, SavedRow, Year, YearSummary } from './clients'
import { transactionCount } from './clientRules.ts'
import { leftOut, longDate, money } from './ledger.ts'

// 30 Sep 2025; "No date" when there is none.
export const fullDate = (iso: string | null | undefined): string => (iso ? longDate(iso) : 'No date')

// How the books compare with the latest statement of the year. The difference is the books less the statement.
// lines: how many of the account's statement lines the year holds. With lines and no balance to check, its statements
// print none (a CSV export without a balance column), which is not the same as having no statement.
export function bankCheckText(c: BankCheck, lines = 0): string {
  if (c.statement === null || c.difference === null || c.statement_date === null) {
    return lines ? 'Its statements print no balance, so the books can\'t be checked against them.' : 'No statement this year.'
  }
  const on = `the statement of ${fullDate(c.statement_date)}`
  const difference = Number(c.difference)
  if (difference === 0) return `Agrees with ${on}.`
  return `${money(c.difference.replace(/^-/, ''))} ${difference < 0 ? 'less' : 'more'} in the books than ${on}.`
}

// A balance as a statement prints it, in words: a bank account below nothing is overdrawn, and a card's balance is
// what is owed on it (in credit when the card company owes the client).
export function bankBalance(value: string, kind: BankCheck['kind']): string {
  const amount = Number(value)
  const size = money(Math.abs(amount).toFixed(2))
  if (kind === 'credit_card') return amount < 0 ? `${size} in credit` : `${size} owed`
  return amount < 0 ? `${size} overdrawn` : size
}

// What the page says when the bank check cannot be worked out because rows need fixing. The API's message lists the
// problems, each naming its row, after "before the trial balance:" and apart by "; "; the notice gives the first.
export function bankCheckNotice(message: string): string {
  const listed = message.split('before the trial balance: ')
  const first = listed.length > 1 ? listed[listed.length - 1].split('; ')[0] : message
  return `The bank check needs the trial balance. ${first.charAt(0).toUpperCase()}${first.slice(1)}`
}

// The account a row with no bank account of its own (a receipt, say) is paid from: the first current account.
export const defaultBank = (client: Client): string | null =>
  (client.bank_accounts.find(a => a.kind === 'current') ?? client.bank_accounts[0])?.code ?? null

// The year's rows on an account's statements, and the lines on another account's statement that are coded to it
// (transfers in), by date.
export function linesFor(ledger: Ledger, code: string): SavedRow[] {
  const fallback = defaultBank(ledger.client)
  return ledger.transactions
    .filter(row => row.document_type === 'statement' && ((row.bank_account ?? fallback) === code || row.account_code === code))
    .sort((a, b) => (a.date ?? '9999').localeCompare(b.date ?? '9999'))
}

// What the Bank section says of an account's lines: how many are in the books, and how many of those it lists were
// left out of them (listed crossed out, as the Transactions table does), so the count adds up to the books.
export function linesCount(lines: SavedRow[], account: string): string {
  const left = lines.filter(leftOut).length
  return `${transactionCount(lines.length - left)} on ${account}${left ? `, ${left} left out` : ''}`
}

export function splitInvoices(list: InvoiceSummary[]): { sales: InvoiceSummary[]; purchases: InvoiceSummary[] } {
  return { sales: list.filter(i => i.kind === 'sale'), purchases: list.filter(i => i.kind === 'purchase') }
}

// Money in whole pence, so sums are exact. A blank or unreadable amount counts as nothing.
const pence = (amount: string): number => Math.round(Number(amount) * 100) || 0
const pounds = (p: number): string => `${p < 0 ? '-' : ''}${money((Math.abs(p) / 100).toFixed(2))}`

const DEBTORS = '1100'
const CREDITORS = '2100'

// What is wrong with a first year's opening balances, in the words the server uses (books.check_opening): debits
// and credits are the same, and the unpaid invoices add up to Debtors and Creditors. Empty when all is well.
export function openingErrors(o: OpeningBalances): string[] {
  const errors: string[] = []
  const debits = o.lines.reduce((sum, l) => sum + pence(l.debit), 0)
  const credits = o.lines.reduce((sum, l) => sum + pence(l.credit), 0)
  if (debits !== credits) errors.push(`Opening debits ${pounds(debits)} and credits ${pounds(credits)} must be the same.`)
  const balance = (code: string) => o.lines.filter(l => l.code === code).reduce((sum, l) => sum + pence(l.debit) - pence(l.credit), 0)
  const owed = (direction: 'in' | 'out') => o.unpaid.filter(i => i.direction === direction).reduce((sum, i) => sum + pence(i.amount), 0)
  // Fewer is allowed: what is not listed is brought forward as one balance, not itemised.
  if (owed('in') > balance(DEBTORS)) {
    errors.push(`The unpaid invoices from customers add up to ${pounds(owed('in'))}, more than Debtors, which is ${pounds(balance(DEBTORS))}.`)
  }
  if (owed('out') > -balance(CREDITORS)) {
    errors.push(`The unpaid bills from suppliers add up to ${pounds(owed('out'))}, more than Creditors, which is ${pounds(-balance(CREDITORS))}.`)
  }
  return errors
}

// What an accountant would settle before locking a year, in words: rows still to review, rows with no date, money
// left in Suspense, a bank account that doesn't agree with its statement, and statements the books don't have.
// Closing is still allowed; nothing here is carried forward silently.
export function closeWarnings(summary: Pick<YearSummary, 'to_review' | 'bank' | 'missing_paperwork'> | null,
                              result: TrialBalanceResult | null, rows: { date: string | null }[]): string[] {
  const found: string[] = []
  const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
  if (summary?.to_review) found.push(`${count(summary.to_review, 'row is', 'rows are')} still to review.`)
  const undated = rows.filter(row => !row.date).length
  if (undated) found.push(`${count(undated, 'row has', 'rows have')} no date.`)
  const suspense = result?.lines.find(line => line.code === '9998')
  const held = suspense ? Number(suspense.debit) - Number(suspense.credit) : 0
  if (held) found.push(`${money(Math.abs(held).toFixed(2))} is in Suspense, and will be carried into the next year.`)
  for (const check of summary?.bank ?? []) {
    if (check.difference && Number(check.difference) !== 0) {
      found.push(`${check.name} is ${money(Math.abs(Number(check.difference)).toFixed(2))} away from its statement.`)
    }
  }
  for (const missing of summary?.missing_paperwork ?? []) found.push(missing)
  return found
}

export const closeQuestion = (year: Year, warnings: string[] = []): string =>
  (warnings.length ? `Before you close:\n${warnings.map(w => `• ${w}`).join('\n')}\n\n` : '')
  + `Close the year to ${longDate(year.end)}? Its figures are locked and carried into the next year. You can reopen it later.`

export interface TrialRow {
  code: string
  name: string
  type: string
  heading?: string           // where it goes in the accounts (accounts.Heading on the API), from its closing balance
  opening: number            // each in pence, a debit positive and a credit negative
  movement: number
  closing: number
}

// The year's accounts with what each opened with, moved by and closed with, by account code.
export function trialRows(result: TrialBalanceResult): TrialRow[] {
  const net = (l: { debit: string; credit: string }) => pence(l.debit) - pence(l.credit)
  const rows = new Map<string, TrialRow>()
  const rowOf = (l: { code: string; name: string; type: string; heading?: string }) => {
    if (!rows.has(l.code)) rows.set(l.code, { code: l.code, name: l.name, type: l.type, heading: l.heading, opening: 0, movement: 0, closing: 0 })
    return rows.get(l.code)!
  }
  for (const l of result.opening ?? []) rowOf(l).opening = net(l)
  for (const l of result.lines) Object.assign(rowOf(l), { closing: net(l), heading: l.heading || rowOf(l).heading })
  return [...rows.values()].sort((a, b) => a.code.localeCompare(b.code))
    .map(r => ({ ...r, movement: r.closing - r.opening }))
}

// £1,200.00 Dr for a debit balance, £300.00 Cr for a credit one; a dash for nothing.
export const balanceText = (p: number): string => (p === 0 ? '—' : `${pounds(Math.abs(p))} ${p > 0 ? 'Dr' : 'Cr'}`)

// The accounts opening balances can go on: the chart's assets, liabilities and equity (income and cost accounts are
// refused), less the bank accounts and cards (12xx) the client does not have.
export const openingAccounts = (chart: AccountChoice[], client: Client): AccountChoice[] =>
  chart.filter(a => ['asset', 'liability', 'equity'].includes(a.type)
    && (!a.code.startsWith('12') || client.bank_accounts.some(b => b.code === a.code)))
    .sort((a, b) => a.code.localeCompare(b.code))


// A journal as a person types it: a day, what it is for, the account to debit, the one to credit, and the amount.
export interface JournalDraft { date: string; description: string; debit: string; credit: string; amount: string }

export function journalErrors(draft: JournalDraft): Partial<Record<keyof JournalDraft, string>> {
  const errors: Partial<Record<keyof JournalDraft, string>> = {}
  if (!draft.date) errors.date = 'Enter the date'
  if (!draft.description.trim()) errors.description = 'Say what the journal is for'
  if (!draft.debit) errors.debit = 'Choose the account to debit'
  if (!draft.credit) errors.credit = 'Choose the account to credit'
  else if (draft.credit === draft.debit) errors.credit = 'Choose a different account from the debit'
  if (!/^\d+(\.\d{1,2})?$/.test(draft.amount.trim()) || Number(draft.amount) <= 0) errors.amount = 'Enter an amount above zero, like 525.00'
  return errors
}

// The row the API books a journal from: money out debits its account and credits its contra account.
export const journalRow = (draft: JournalDraft) => ({
  date: draft.date, description: draft.description.trim(), direction: 'out', gross: Number(draft.amount).toFixed(2),
  vat: null, vat_treatment: null, vat_posted: null, net: null, account_code: draft.debit,
  contra_account_code: draft.credit, currency: 'GBP', source: 'manual', method: 'user', evidence: null,
  document_type: 'journal', issues: [],
})

// One line of a statement: an account, or a total, with its amount in pence as the statement reads it.
export interface StatementLine { label: string; amount: number; total?: boolean }
export interface Statements { profitAndLoss: StatementLine[]; balanceSheet: StatementLine[]; agrees: boolean }

// The headings of the Companies Act formats each account goes under (accounts.Heading on the API).
export const HEADINGS = {
  turnover: 'Turnover', costOfSales: 'Cost of sales', administrative: 'Administrative expenses',
  otherIncome: 'Other operating income', interestReceivable: 'Interest receivable and similar income',
  interestPayable: 'Interest payable and similar charges', tax: 'Tax on profit', intangible: 'Intangible assets',
  tangible: 'Tangible assets', investments: 'Investments', stocks: 'Stocks', debtors: 'Debtors',
  cash: 'Cash at bank and in hand', creditorsShort: 'Creditors: amounts falling due within one year',
  creditorsLong: 'Creditors: amounts falling due after more than one year',
  membersDebt: 'Loans and other debts due to members', capital: 'Capital and reserves',
} as const

// An account's heading: the API's, or for an older API's line without one, the usual one for its code and type
// (Suspense on the side its balance is on).
export function headingOf(r: TrialRow): string {
  if (r.heading) return r.heading
  const h = HEADINGS
  if (r.code === '9998') return r.closing > 0 ? h.debtors : h.creditorsShort
  if (r.type === 'income') return r.code < '4900' ? h.turnover : h.otherIncome
  if (r.type === 'expense') return r.code.startsWith('5') ? h.costOfSales : h.administrative
  if (r.type === 'equity') return h.capital
  if (r.type === 'liability') return h.creditorsShort
  return r.code < '1000' ? h.tangible : r.code < '1100' ? h.stocks : r.code < '1200' ? h.debtors : h.cash
}

// The year's profit and loss account and its closing balance sheet, from the trial balance, under the headings of
// the Companies Act formats, as the Excel export lays them out (export.statement_lines). Income and costs are
// shown positive, and so are assets and what is owed. Each heading lists its accounts and its total; the profit
// lines (gross, operating, before tax) show only where there is something between them. Net assets equal capital
// and reserves with the year's profit, an LLP's debts due to its members among them. agrees: they are equal.
export function statements(rows: TrialRow[]): Statements {
  const h = HEADINGS
  const used = rows.filter(r => r.closing !== 0)
  const sum = (lines: StatementLine[]) => lines.reduce((total, l) => total + l.amount, 0)
  const of = (heading: string) => used.filter(r => headingOf(r) === heading)
  const block = (out: StatementLine[], heading: string, sign: 1 | -1): number => {
    const lines = of(heading).map(r => ({ label: `${r.code} ${r.name}`, amount: sign * r.closing }))
    if (lines.length) out.push(...lines, { label: heading, amount: sum(lines), total: true })
    return sum(lines)
  }
  const total = (out: StatementLine[], label: string, amount: number) => out.push({ label, amount, total: true })

  const pl: StatementLine[] = []
  const turnover = block(pl, h.turnover, -1)
  const cost = block(pl, h.costOfSales, 1)
  if (of(h.costOfSales).length) total(pl, 'Gross profit', turnover - cost)
  const admin = block(pl, h.administrative, 1)
  const operating = turnover - cost - admin + block(pl, h.otherIncome, -1)
  if ([h.interestReceivable, h.interestPayable, h.tax].some(x => of(x).length)) {
    total(pl, operating < 0 ? 'Operating loss' : 'Operating profit', operating)
  }
  const received = block(pl, h.interestReceivable, -1)
  const beforeTax = operating + received - block(pl, h.interestPayable, 1)
  if (of(h.tax).length) total(pl, beforeTax < 0 ? 'Loss before tax' : 'Profit before tax', beforeTax)
  const profit = beforeTax - block(pl, h.tax, 1)
  total(pl, profit < 0 ? 'Net loss' : 'Net profit', profit)

  const bs: StatementLine[] = []
  const fixedHeadings = [h.intangible, h.tangible, h.investments]
  const fixed = fixedHeadings.reduce((t, x) => t + block(bs, x, 1), 0)
  if (fixedHeadings.some(x => of(x).length)) total(bs, 'Fixed assets', fixed)
  const current = [h.stocks, h.debtors, h.cash].reduce((t, x) => t + block(bs, x, 1), 0)
  total(bs, 'Current assets', current)
  const short = block(bs, h.creditorsShort, -1)
  total(bs, current >= short ? 'Net current assets' : 'Net current liabilities', current - short)
  const long = block(bs, h.creditorsLong, -1)
  const netAssets = fixed + current - short - long
  total(bs, 'Net assets', netAssets)
  const members = block(bs, h.membersDebt, -1)
  const equity = of(h.capital).map(r => ({ label: `${r.code} ${r.name}`, amount: -r.closing }))
  bs.push(...equity, { label: profit < 0 ? 'Loss for the year' : 'Profit for the year', amount: profit })
  const capital = members + sum(equity) + profit
  total(bs, 'Capital and reserves', capital)
  return { profitAndLoss: pl, balanceSheet: bs, agrees: netAssets === capital }
}

// A statement's amount: £1,200.00, or (£300.00) for a negative one; a dash for nothing.
export const statementAmount = (p: number): string =>
  (p === 0 ? '—' : p < 0 ? `(${money((Math.abs(p) / 100).toFixed(2))})` : money((p / 100).toFixed(2)))


// How long what is still owed on the invoices has been owed, by the invoice's date, at a day (today, or the year's
// end once it has passed): the totals up to 30 days old, 31 to 60, 61 to 90 and over 90, in pence. A credit note
// counts against what is owed. An invoice with no date is counted as the oldest.
export interface Ageing { total: number; upTo30: number; upTo60: number; upTo90: number; over90: number }

export const daysOld = (date: string | null, asAt: string): number | null =>
  (date ? Math.max(0, Math.round((Date.parse(asAt) - Date.parse(date)) / 86400000)) : null)

// Once the year has ended (atYearEnd), what was owed on its last day, as its Debtors and Creditors hold it: an
// invoice paid since was still owed then.
export function ageing(invoices: InvoiceSummary[], asAt: string, atYearEnd = false): Ageing {
  const found: Ageing = { total: 0, upTo30: 0, upTo60: 0, upTo90: 0, over90: 0 }
  for (const invoice of invoices) {
    const owed = pence(atYearEnd ? invoice.owed_at_year_end : invoice.owed) * (invoice.credit_note ? -1 : 1)
    if (!owed) continue
    const days = daysOld(invoice.date, asAt)
    found.total += owed
    found[days === null || days > 90 ? 'over90' : days > 60 ? 'upTo90' : days > 30 ? 'upTo60' : 'upTo30'] += owed
  }
  return found
}

// "£2,400.00 owed at 10 Nov 2026: £2,400.00 over 90 days", leaving out the ages nothing is owed in.
export function ageingText(a: Ageing, asAt: string): string {
  if (!a.total) return 'Nothing owed.'
  const parts = [[a.upTo30, 'up to 30 days'], [a.upTo60, '31 to 60 days'], [a.upTo90, '61 to 90 days'], [a.over90, 'over 90 days']]
    .filter(([amount]) => amount).map(([amount, label]) => `${pounds(amount as number)} ${label}`)
  return `${pounds(a.total)} owed at ${fullDate(asAt)}: ${parts.join(', ')}.`
}


// The periods a year's VAT figures can be worked out for: the whole year, then its four quarters, each three months
// on from the year's start. (A client's own VAT quarters may be staggered differently; these follow its year.)
export interface VatPeriod { label: string; start: string; end: string }

export function vatPeriods(year: Year): VatPeriod[] {
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  const plusMonths = (from: string, months: number) => {
    const [y, m, d] = from.split('-').map(Number)
    return new Date(Date.UTC(y, m - 1 + months, d))
  }
  const quarters = [0, 1, 2, 3].map(q => {
    const start = iso(plusMonths(year.start, q * 3))
    const next = plusMonths(year.start, (q + 1) * 3)
    const end = q === 3 ? year.end : iso(new Date(next.getTime() - 86400000))
    return { label: `${fullDate(start)} to ${fullDate(end)}`, start, end }
  })
  return [{ label: `Whole year: ${year.label}`, start: year.start, end: year.end }, ...quarters]
}

// What each box of the VAT return is, as the return words it.
export const VAT_BOXES: [keyof Pick<import('./clients').VatFigures, 'box1' | 'box2' | 'box3' | 'box4' | 'box5' | 'box6' | 'box7' | 'box8' | 'box9'>, string][] = [
  ['box1', 'VAT due on sales and other outputs'],
  ['box2', 'VAT due on acquisitions of goods into Northern Ireland from the EU'],
  ['box3', 'Total VAT due (box 1 plus box 2)'],
  ['box4', 'VAT reclaimed on purchases and other inputs'],
  ['box5', 'Net VAT to pay, or to reclaim (box 3 less box 4)'],
  ['box6', 'Total sales and other outputs, excluding VAT'],
  ['box7', 'Total purchases and other inputs, excluding VAT'],
  ['box8', 'Goods supplied to the EU from Northern Ireland, excluding VAT'],
  ['box9', 'Goods acquired from the EU into Northern Ireland, excluding VAT'],
]

// A box's figure as the return takes it: boxes 6 to 9 in whole pounds, the others in pounds and pence; box 5 says
// which way it goes.
export function vatBoxText(box: string, value: string): string {
  const amount = Number(value)
  if (['box6', 'box7', 'box8', 'box9'].includes(box)) return `£${Math.round(amount).toLocaleString('en-GB')}`
  if (box === 'box5') return amount < 0 ? `${money(Math.abs(amount).toFixed(2))} to reclaim` : `${money(value)} to pay`
  return money(value)
}
