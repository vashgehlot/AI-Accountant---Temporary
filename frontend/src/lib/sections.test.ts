// Run with: npm test (Node's own test runner; Node strips the TypeScript types itself).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import type { BankCheck, Client, InvoiceSummary, Ledger, OpeningBalances, SavedRow, Year } from './clients.ts'
import type { TrialBalanceResult } from './api.ts'
import {
  HEADINGS, ageing, ageingText, vatBoxText, vatPeriods, bankBalance, bankCheckNotice, bankCheckText, journalErrors, journalRow, statementAmount, statements, closeQuestion, closeWarnings, defaultBank, fullDate, linesCount, linesFor, openingAccounts, openingErrors, splitInvoices, trialRows,
} from './sections.ts'

const check = (change: Partial<BankCheck> = {}): BankCheck => ({
  code: '1200', name: 'Current', kind: 'current', books: '100.00', statement: '100.00', statement_date: '2025-09-30',
  difference: '0.00', ...change,
})

const inv = (kind: 'sale' | 'purchase'): InvoiceSummary => ({
  ref: kind, kind, counterparty: 'Acme', number: '1', date: '2025-05-01', total: '10.00', paid: '0.00', owed: '10.00',
  owed_at_year_end: '10.00', paid_by: [], brought_forward: false,
})

test('the bank check says whether the books agree with the statement', () => {
  assert.equal(bankCheckText(check({ difference: '0.00', statement_date: '2025-09-30' })), 'Agrees with the statement of 30 Sep 2025.')
  assert.equal(bankCheckText(check({ difference: '-25.00', statement_date: '2025-09-30' })), '£25.00 less in the books than the statement of 30 Sep 2025.')
  assert.equal(bankCheckText(check({ difference: '1200.50', statement_date: '2025-09-30' })), '£1,200.50 more in the books than the statement of 30 Sep 2025.')
  assert.equal(bankCheckText(check({ statement: null, difference: null, statement_date: null })), 'No statement this year.')
  assert.equal(bankCheckText(check({ statement: null, difference: null, statement_date: null }), 9),
               "Its statements print no balance, so the books can't be checked against them.")
})

test('an overdrawn account and a card say which way their balance is', () => {
  assert.equal(bankBalance('-2887.11', 'current'), '£2,887.11 overdrawn')
  assert.equal(bankBalance('1599.81', 'current'), '£1,599.81')
  assert.equal(bankBalance('850.00', 'credit_card'), '£850.00 owed')
  assert.equal(bankBalance('-20.00', 'credit_card'), '£20.00 in credit')
})

test('invoices split into sales and purchases', () => {
  const { sales, purchases } = splitInvoices([inv('sale'), inv('purchase'), inv('sale')])
  assert.equal(sales.length, 2); assert.equal(purchases.length, 1)
})

test('dates are written 30 Sep 2025, and a missing one says so', () => {
  assert.equal(fullDate('2025-09-30'), '30 Sep 2025')
  assert.equal(fullDate('2026-03-01'), '1 Mar 2026')
  assert.equal(fullDate(null), 'No date')
})

test('the notice names the first problem that stops the bank check', () => {
  assert.equal(bankCheckNotice('2 problem(s) must be fixed before the trial balance: BT (1 Sep 2026, £72.00): The date is missing.; Xero (2 Sep 2026, £36.00): The total is wrong.'),
               'The bank check needs the trial balance. BT (1 Sep 2026, £72.00): The date is missing.')
  assert.equal(bankCheckNotice('Fix the earlier years first: 1 problem(s) must be fixed before the trial balance: AWS (3 Jan 2026, £500.00): Unknown account.'),
               'The bank check needs the trial balance. AWS (3 Jan 2026, £500.00): Unknown account.')
  assert.equal(bankCheckNotice('Something else went wrong.'), 'The bank check needs the trial balance. Something else went wrong.')
})

const client = (kinds: ('current' | 'savings')[]): Client => ({
  id: 1, name: 'Acme', business_type: 'limited_company', contact_name: '', contact_email: '', contact_phone: '',
  vat_registered: false, first_year_end: '2026-03-31', archived: false, archived_at: null, created_at: '', updated_at: '',
  bank_accounts: kinds.map((kind, i) => ({ code: kind === 'current' ? `120${i}` : `121${i}`, name: `Account ${i}`, kind })),
})

let nextId = 1
const row = (change: Partial<SavedRow>): SavedRow => ({
  id: nextId++, upload_id: 1, edited: false, original: null,
  date: '2025-05-01', description: 'x', direction: 'out', gross: '10.00', vat: null, vat_treatment: null, vat_posted: null, net: null,
  account_code: '7100', contra_account_code: null, currency: 'GBP', source: 'pdf', method: 'llm', evidence: null, issues: [],
  document_type: 'statement', bank_account: '1200', ...change,
})
const ledgerOf = (c: Client, rows: SavedRow[]) => ({ client: c, transactions: rows }) as unknown as Ledger

test('the default bank is the first current account, else the first account', () => {
  assert.equal(defaultBank(client(['savings', 'current'])), '1201')
  assert.equal(defaultBank(client(['savings'])), '1210')
})

test('an account shows its statement lines and the transfers into it from another account', () => {
  const c = client(['current', 'savings'])   // codes 1200 and 1211
  const own = row({ bank_account: '1200', description: 'own' })
  const unset = row({ bank_account: null, description: 'default account' })
  const other = row({ bank_account: '1211', description: 'savings line' })
  const transferIn = row({ bank_account: '1211', account_code: '1200', description: 'transfer to current' })
  const receipt = row({ bank_account: null, document_type: 'receipt', description: 'a receipt' })
  const ledger = ledgerOf(c, [own, unset, other, transferIn, receipt])
  assert.deepEqual(linesFor(ledger, '1200').map(r => r.description), ['own', 'default account', 'transfer to current'])
  assert.deepEqual(linesFor(ledger, '1211').map(r => r.description), ['savings line', 'transfer to current'])
})

test("an account's count is of the lines in the books, and says how many it lists left out", () => {
  // The Bank page counted a bank line a decision left out, so its lines did not add up to the books.
  const kept = [row({}), row({ id: 2 })]
  assert.equal(linesCount(kept, 'Current'), '2 transactions on Current')
  assert.equal(linesCount([...kept, row({ id: 3, excluded: true }), row({ id: 4, superseded_by: 'd1' })], 'Current'),
               '2 transactions on Current, 2 left out')
  assert.equal(linesCount([row({ excluded: true })], 'Current'), '0 transactions on Current, 1 left out')
})

const year = (end: string): Year => ({ start: '2025-04-01', end, label: `Year to ${end}`, closed: false })

test('opening balances must balance', () => {
  assert.deepEqual(openingErrors({ lines: [{ code: '1200', debit: '10.00', credit: '0.00' }], unpaid: [] }),
    ['Opening debits £10.00 and credits £0.00 must be the same.'])
  assert.deepEqual(openingErrors({ lines: [], unpaid: [] }), [])
})

test('the unpaid invoices must make up Debtors and Creditors', () => {
  const item = (direction: 'in' | 'out', amount: string) => ({ id: direction + amount, direction, counterparty: 'Acme', amount, number: null, date: null })
  const balanced = (o: Partial<OpeningBalances>): OpeningBalances => ({
    lines: [
      { code: '1100', debit: '300.00', credit: '0.00' }, { code: '2100', debit: '0.00', credit: '120.50' },
      { code: '3100', debit: '0.00', credit: '179.50' },
    ],
    unpaid: [item('in', '300.00'), item('out', '120.50')], ...o,
  })
  assert.deepEqual(openingErrors(balanced({})), [])
  // fewer than the balance, or none, is allowed: the rest is brought forward as one balance
  assert.deepEqual(openingErrors(balanced({ unpaid: [item('in', '250.00'), item('out', '120.50')] })), [])
  assert.deepEqual(openingErrors(balanced({ unpaid: [] })), [])
  assert.deepEqual(openingErrors(balanced({ unpaid: [item('in', '1300.00'), item('out', '120.50')] })),
    ['The unpaid invoices from customers add up to £1,300.00, more than Debtors, which is £300.00.'])
})

test('closing a year asks first', () => {
  assert.match(closeQuestion(year('2026-03-31')), /^Close the year to 31 Mar 2026\?/)
  assert.equal(closeQuestion(year('2026-03-31')),
    'Close the year to 31 Mar 2026? Its figures are locked and carried into the next year. You can reopen it later.')
})

test('closing a year says first what is still unsettled in it', () => {
  const tb = { lines: [{ code: '9998', name: 'Suspense', type: 'liability', debit: '1624.20', credit: '0.00' }],
               total_debits: '0', total_credits: '0', is_balanced: true } as TrialBalanceResult
  const summary = { to_review: 5, bank: [check({ name: 'Lloyds current', difference: '-54.85' }), check()],
                    missing_paperwork: ['Amex card: no statement for this year yet.'] }
  const warnings = closeWarnings(summary, tb, [{ date: null }, { date: '2026-03-01' }])
  assert.deepEqual(warnings, [
    '5 rows are still to review.', '1 row has no date.',
    '£1,624.20 is in Suspense, and will be carried into the next year.',
    'Lloyds current is £54.85 away from its statement.', 'Amex card: no statement for this year yet.'])
  assert.match(closeQuestion(year('2026-04-05'), warnings), /^Before you close:\n• 5 rows are still to review\.\n/)
  assert.deepEqual(closeWarnings({ to_review: 0, bank: [check()], missing_paperwork: [] }, null, []), [])
})

test('the trial balance shows each account opening, moving and closing', () => {
  const line = (code: string, debit: string, credit: string) => ({ code, name: `Account ${code}`, type: 'asset', debit, credit })
  const result = {
    opening: [line('1200', '100.00', '0.00'), line('3100', '0.00', '100.00')],
    lines: [line('1200', '70.00', '0.00'), line('3100', '0.00', '100.00'), line('7100', '30.00', '0.00')],
  } as unknown as TrialBalanceResult
  assert.deepEqual(trialRows(result).map(r => [r.code, r.opening, r.movement, r.closing]), [
    ['1200', 10000, -3000, 7000],
    ['3100', -10000, 0, -10000],
    ['7100', 0, 3000, 3000],
  ])
})

test('opening balances are offered balance sheet accounts and the client\'s own bank accounts', () => {
  const account = (code: string, type: string) => ({ code, name: code, type, vat: 'outside_scope' })
  const chart = [account('7100', 'expense'), account('4000', 'income'), account('3200', 'equity'), account('1100', 'asset'),
                 account('1201', 'asset'), account('1200', 'asset'), account('2100', 'liability')]
  assert.deepEqual(openingAccounts(chart, client(['current'])).map(a => a.code), ['1100', '1200', '2100', '3200'])
})


test('a journal needs a date, two different accounts and an amount, and books as money out between them', () => {
  const draft = { date: '2027-03-31', description: ' Depreciation for the year ', debit: '8000', credit: '0031', amount: '525' }
  assert.deepEqual(journalErrors(draft), {})
  assert.deepEqual(Object.keys(journalErrors({ ...draft, credit: '8000', amount: '-5', date: '' })).sort(), ['amount', 'credit', 'date'])
  const row = journalRow(draft)
  assert.deepEqual([row.document_type, row.direction, row.account_code, row.contra_account_code, row.gross, row.description],
                   ['journal', 'out', '8000', '0031', '525.00', 'Depreciation for the year'])
})

test('the profit and loss and the balance sheet come from the trial balance, and agree', () => {
  const r = (code: string, type: string, closing: number) => ({ code, name: `A${code}`, type, opening: 0, movement: closing, closing })
  // pence, debits positive: equipment 2,000, bank 500 overdrawn, held in Suspense 240, creditors 300, shares 100,
  // sales 3,000, purchases 1,000, rent 660
  const made = statements([r('0030', 'asset', 200000), r('1200', 'asset', -50000), r('9998', 'liability', 24000),
                           r('2100', 'liability', -30000), r('3000', 'equity', -10000), r('4000', 'income', -300000),
                           r('5000', 'expense', 100000), r('7100', 'expense', 66000)])
  const of = (lines: { label: string; amount: number }[], label: string) => lines.find(l => l.label === label)?.amount
  assert.equal(of(made.profitAndLoss, 'Gross profit'), 200000)
  assert.equal(of(made.profitAndLoss, 'Net profit'), 134000)
  assert.equal(of(made.balanceSheet, 'Current assets'), -26000)     // the overdraft, and what Suspense holds in debit
  assert.equal(of(made.balanceSheet, 'Debtors'), 24000)
  assert.equal(of(made.balanceSheet, 'Creditors: amounts falling due within one year'), 30000)
  assert.equal(of(made.balanceSheet, 'Net assets'), 144000)
  assert.equal(of(made.balanceSheet, 'Capital and reserves'), 144000)
  assert.ok(made.agrees)
  assert.deepEqual([statementAmount(134000), statementAmount(-26000), statementAmount(0)], ['£1,340.00', '(£260.00)', '—'])
})


test('once the year has ended, what is aged is what was owed at its end, not what is owed now', () => {
  // Mendip's £16,380 invoice of 15 Feb 2024, paid on 2 Apr: owed at 31 Mar 2024, though nothing is owed on it now.
  const paidSince: InvoiceSummary = { ...inv('sale'), date: '2024-02-15', total: '16380.00', paid: '16380.00',
    owed: '0.00', owed_at_year_end: '16380.00' }
  const a = ageing([paidSince], '2024-03-31', true)
  assert.equal(ageingText(a, '2024-03-31'), '£16,380.00 owed at 31 Mar 2024: £16,380.00 31 to 60 days.')
  assert.equal(ageing([paidSince], '2024-03-31').total, 0)   // a year still running: what is owed now
})

test('what is owed is aged by the invoice date, a credit note counting against it', () => {
  const owed = (date: string | null, amount: string, credit_note = false): InvoiceSummary =>
    ({ ...inv('sale'), date, owed: amount, credit_note })
  const a = ageing([owed('2026-10-20', '100.00'), owed('2026-09-20', '200.00'), owed('2026-06-01', '300.00'),
                    owed(null, '50.00'), owed('2026-10-25', '20.00', true), owed('2026-10-01', '0.00')], '2026-11-10')
  assert.deepEqual(a, { total: 63000, upTo30: 8000, upTo60: 20000, upTo90: 0, over90: 35000 })
  assert.equal(ageingText(a, '2026-11-10'), '£630.00 owed at 10 Nov 2026: £80.00 up to 30 days, £200.00 31 to 60 days, £350.00 over 90 days.')
  assert.equal(ageingText(ageing([], '2026-11-10'), '2026-11-10'), 'Nothing owed.')
})


test('a year has its whole self and four quarters to work VAT figures for', () => {
  const periods = vatPeriods({ start: '2026-04-01', end: '2027-03-31', label: 'Year to 31 Mar 2027', closed: false } as Year)
  assert.deepEqual(periods.map(p => [p.start, p.end]), [
    ['2026-04-01', '2027-03-31'], ['2026-04-01', '2026-06-30'], ['2026-07-01', '2026-09-30'],
    ['2026-10-01', '2026-12-31'], ['2027-01-01', '2027-03-31']])
  assert.equal(periods[3].label, '1 Oct 2026 to 31 Dec 2026')
  const taxYear = vatPeriods({ start: '2025-04-06', end: '2026-04-05', label: 'Year to 5 Apr 2026', closed: false } as Year)
  assert.deepEqual(taxYear.slice(1).map(p => [p.start, p.end]), [
    ['2025-04-06', '2025-07-05'], ['2025-07-06', '2025-10-05'], ['2025-10-06', '2026-01-05'], ['2026-01-06', '2026-04-05']])
  assert.deepEqual([vatBoxText('box1', '800.00'), vatBoxText('box5', '-12.12'), vatBoxText('box5', '491.67'), vatBoxText('box6', '6500.49')],
                   ['£800.00', '£12.12 to reclaim', '£491.67 to pay', '£6,500'])
})

test('the statements follow the API\'s headings: tax after profit before tax, long-term debt apart', () => {
  const r = (code: string, type: string, closing: number, heading: string) =>
    ({ code, name: `A${code}`, type, heading, opening: 0, movement: closing, closing })
  const h = HEADINGS
  const made = statements([r('0030', 'asset', 150000, h.tangible), r('1200', 'asset', 300000, h.cash),
                           r('2250', 'liability', 40000, h.debtors), r('2100', 'liability', -70000, h.creditorsShort),
                           r('2320', 'liability', -130000, h.creditorsShort), r('2301', 'liability', -150000, h.creditorsLong),
                           r('3000', 'equity', -10000, h.capital), r('4000', 'income', -1000000, h.turnover),
                           r('5000', 'expense', 400000, h.costOfSales), r('7100', 'expense', 200000, h.administrative),
                           r('7903', 'expense', 15000, h.interestPayable), r('8800', 'expense', 130000, h.tax),
                           r('3200', 'equity', 125000, h.capital)])
  const of = (lines: { label: string; amount: number }[], label: string) => lines.find(l => l.label === label)?.amount
  const labels = made.profitAndLoss.map(l => l.label)
  assert.deepEqual([of(made.profitAndLoss, 'Gross profit'), of(made.profitAndLoss, 'Operating profit'),
                    of(made.profitAndLoss, 'Profit before tax'), of(made.profitAndLoss, 'Net profit')],
                   [600000, 400000, 385000, 255000])
  assert.ok(labels.indexOf('Profit before tax') < labels.indexOf('8800 A8800'))
  assert.equal(of(made.balanceSheet, 'Debtors'), 40000)   // a director who owes the company is its debtor
  assert.equal(of(made.balanceSheet, 'Creditors: amounts falling due after more than one year'), 150000)
  assert.equal(of(made.balanceSheet, 'Net assets'), 150000 + 340000 - 200000 - 150000)
  assert.ok(made.agrees)
})
