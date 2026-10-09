// Run with: npm test (Node's own test runner; Node strips the TypeScript types itself).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import type { Transaction } from './api.ts'
import { possibleDuplicates } from './duplicates.ts'
import { aboutAnotherRow, accountName, apartChange, apartStatus, canBeApart, checkHover, issueHeading, issueTitle, kindOf, paymentRowOf, reviewSummary,
         rowStatus, showLabel, takesLines, totalsOf } from './ledger.ts'

// A transaction as the API returns it (an unpaid rent bill), with what a test needs changed.
const tx = (change: Partial<Transaction> = {}): Transaction => ({
  date: '2026-10-01', description: 'October rent', direction: 'out', gross: '12000.00', vat: '2000.00',
  vat_treatment: null, vat_posted: '2000.00', net: '10000.00', account_code: '7100', contra_account_code: '2100',
  currency: 'GBP', source: 'text', method: 'llm', evidence: null, issues: [], document_type: 'invoice',
  counterparty: 'Business Cube', document_ref: 'bill', owed: '12000.00', paid_by: [], ...change,
})

const paidBy = [{ ref: 'line', amount: '12000.00', date: '2026-10-03', description: 'BUSINESS CUBE MGMT' }]

test('an unpaid bill is owed to the supplier, and a paid one says when it was paid', () => {
  assert.deepEqual(rowStatus(tx()).map(s => s.text), ['Unpaid, owed to Business Cube'])
  assert.deepEqual(rowStatus(tx({ owed: '0.00', paid_by: paidBy })).map(s => s.text), ['Paid by bank line on 3 Oct'])
})

test('who owes whom follows the direction of the money, so credit notes read the right way', () => {
  // Final review #5: the text followed the Debtors account instead, so both kinds of credit note read backwards.
  const sale = { account_code: '4000', contra_account_code: '1100', counterparty: 'Harbour & Lane' }
  assert.equal(rowStatus(tx({ ...sale, direction: 'in' }))[0].text, 'Unpaid, owed by Harbour & Lane')
  assert.equal(rowStatus(tx({ ...sale, direction: 'out' }))[0].text, 'Unpaid, owed to Harbour & Lane')
  assert.equal(rowStatus(tx({ direction: 'in', counterparty: 'Clearway' }))[0].text, 'Unpaid, owed by Clearway')
})

test('a choice between documents can also be declined', () => {
  // Final review #2: with only Link buttons, the person had to post the payment wrongly to unblock the trial balance.
  const option = { ref: 'bill', amount: '72.00', date: '2026-09-20', description: 'BT' }
  const [status] = rowStatus(tx({
    document_type: 'statement', owed: null, candidates: [[option], [{ ...option, ref: 'bill-2' }]],
    issues: [{ code: 'choose_payment', severity: 'error', message: 'Could pay: … Choose one.' }],
  }))
  assert.equal(status.text, 'Could pay:')
  assert.deepEqual(status.actions.map(a => a.change), [{ link: ['bill'] }, { link: ['bill-2'] }, { link: [] }])
  assert.equal(status.actions[2].label, 'None of these')
})

test('document totals say what is still owed, not only what was billed', () => {
  // Final review #12: "Owed by you £12,000.00" showed for a bill that was already paid.
  const bill = tx({ owed: '0.00', paid_by: paidBy })
  const line = tx({ document_type: 'statement', document_ref: 'line', vat: null, vat_posted: '0.00', net: '12000.00',
                    owed: null, contra_account_code: '1200', paid_against: '2100' })
  assert.deepEqual(totalsOf([bill, line]).map(t => [t.label, t.gross, t.stillOwed]), [
    ['Paid out (bank)', '12000.00', undefined],
    ['Documents, money out', '12000.00', '0.00'],
  ])
})

test('a copy of a document is not booked, or counted, until a person includes it', () => {
  // A reminder repeating a bill's number was booked as a second bill.
  const original = { ref: 'bill', amount: '610.63', date: '2026-03-25', description: 'HML PM Ltd, service charge' }
  const copy = tx({ gross: '610.63', vat: null, vat_posted: '0.00', net: '610.63', owed: null, copy_of: original })
  assert.equal(kindOf(copy), 'not booked')
  assert.deepEqual(rowStatus(copy), [{
    text: 'Same as HML PM Ltd, service charge (£610.63, 25 Mar), not booked. Tick to include it as well',
    actions: [], include: false,
  }])
  assert.deepEqual(totalsOf([copy]), [])
  const included = { ...copy, include: true, owed: '610.63' }
  assert.equal(kindOf(included), 'document')
  assert.deepEqual(rowStatus(included).map(s => s.text), ['Included as well as HML PM Ltd, service charge (£610.63, 25 Mar)',
                                                          'Unpaid, owed to Business Cube'])
})

test('a receipt read twice is not booked twice', () => {
  const copy = tx({ document_type: 'receipt', owed: null, contra_account_code: '1200',
                    copy_of: { ref: 'photo', amount: '7.49', date: '2026-01-02', description: 'Pizza Hut' } })
  assert.equal(kindOf(copy), 'not booked')
})

// An item of a letting agent's statement: the agent holds what it collected until it pays over the net.
const item = (change: Partial<Transaction> = {}): Transaction => tx({
  document_type: 'agent_statement', agent: 'R+R PR Ltd', counterparty: 'R+R PR Ltd', document_ref: 'statement',
  direction: 'out', gross: '111.00', vat: null, vat_posted: '0.00', net: '111.00', account_code: '7603',
  contra_account_code: '1100', document_direction: 'in', owed: '526.75', ...change,
})

test('each item of an agent statement says what the agent still owes the business', () => {
  assert.equal(kindOf(item()), 'document')
  assert.deepEqual(rowStatus(item()).map(s => s.text), ['Unpaid, owed by R+R PR Ltd'])
})

test('an item the agent paid shows the bill it pays, with Unlink', () => {
  const boiler = item({
    counterparty: 'Parkside Heating', gross: '280.00', net: '280.00', paid_against: '2100', owed: '0.00',
    paid_by: [{ ref: 'line', amount: '526.75', date: '2025-05-13', description: 'R+R PR LTD' }],
    pays: [{ ref: 'boiler', amount: '280.00', date: '2025-05-08', description: 'Boiler repair' }],
  })
  assert.deepEqual(rowStatus(boiler), [
    { text: 'Paid by bank line on 13 May', actions: [] },
    { text: 'Pays: Boiler repair (£280.00, 8 May)', actions: [{ label: 'Unlink', change: { link: [] } }] },
  ])
})

test('what an agent statement still owes is counted once, on the side it is owed', () => {
  const rent = item({ direction: 'in', gross: '925.00', net: '925.00', account_code: '4904', counterparty: '22 Telecom' })
  const costs = item({ gross: '398.25', net: '398.25' })
  assert.deepEqual(totalsOf([rent, costs]).map(t => [t.label, t.gross, t.stillOwed]), [
    ['Documents, money out', '398.25', '0.00'],
    ['Documents, money in', '925.00', '526.75'],
  ])
})

test('a bill the agent paid says so, not that a bank line paid it', () => {
  const paid = tx({ owed: '0.00', paid_by: [{ ref: 'item', amount: '280.00', date: '2025-05-09', kind: 'agent_statement',
                                              description: "R+R PR Ltd's statement" }] })
  assert.equal(rowStatus(paid)[0].text, "Paid by R+R PR Ltd's statement on 9 May")
})

test('a card payment its receipt records is booked once, from the receipt', () => {
  // The receipt and its card line were two payments: the meal and the bank were both counted twice.
  const receipt = tx({ document_type: 'receipt', document_ref: 'r', gross: '21.35', vat: '3.56', vat_posted: '3.56',
                       net: '17.79', account_code: '7406', contra_account_code: '1200', owed: null,
                       paid_by: [{ ref: 'card', amount: '21.35', date: '2026-02-23', description: 'MCDONALDS' }] })
  const card = tx({ document_type: 'statement', document_ref: 'card', gross: '21.35', vat: null, vat_posted: '0.00',
                    net: '21.35', account_code: '7406', contra_account_code: '1200', owed: null,
                    recorded_by: { ref: 'r', amount: '21.35', date: '2026-02-22', description: "McDonald's" } })
  assert.equal(kindOf(card), 'not booked')
  assert.deepEqual(rowStatus(card), [{ text: "Booked from the receipt: McDonald's (£21.35, 22 Feb)",
                                       actions: [{ label: 'Unlink', change: { link: [] } }] }])
  assert.deepEqual(rowStatus(receipt).map(s => s.text), ['Paid by card: bank line on 23 Feb'])
  assert.deepEqual(totalsOf([receipt, card]).map(t => [t.label, t.gross]), [['Paid out (bank)', '21.35']])
})

test('a claim line its receipt books is greyed out, with a tick to book it as well', () => {
  const line = tx({ document_type: 'expense_claim', counterparty: 'Jenny Hogg', contra_account_code: '2110',
                    recorded_by: { ref: 'ticket', amount: '157.59', date: '2026-09-07', description: 'Trainline', kind: 'receipt' } })
  assert.equal(kindOf(line), 'not booked')
  assert.deepEqual(rowStatus(line), [{ text: 'Booked from the receipt: Trainline (£157.59, 7 Sept). Tick to book this line as well',
                                       actions: [], include: false }])
})

test('a receipt on an expense claim is owed to the claimant, not paid by the business', () => {
  const receipt = tx({ document_type: 'receipt', owed: null, contra_account_code: '2110', gross: '157.59',
                       claimed_in: { ref: 'claim', amount: '157.59', date: '2026-09-07', description: "Jenny Hogg's expense claim",
                                     kind: 'expense_claim' } })
  assert.equal(kindOf(receipt), 'document')
  assert.deepEqual(rowStatus(receipt).map(s => s.text), ["On Jenny Hogg's expense claim: owed to the claimant"])
  assert.deepEqual(totalsOf([receipt]).map(t => t.label), ['Documents, money out'])
})

test('a claim line ticked to book it as well as its receipt is booked, and can be unticked', () => {
  const line = tx({ document_type: 'expense_claim', counterparty: 'Jenny Hogg', include: true,
                    recorded_by: { ref: 'ticket', amount: '157.59', date: '2026-09-07', description: 'Trainline',
                                   kind: 'receipt' } })
  assert.equal(kindOf(line), 'document')
  assert.deepEqual(rowStatus(line), [{ text: 'Booked as well as the receipt: Trainline (£157.59, 7 Sept). Untick to book '
                                             + 'it from the receipt only', actions: [], include: true }])
  assert.equal(kindOf({ ...line, include: false }), 'not booked')
})

test('a line can be added to any document that prints a total, but not to a bank line', () => {
  // A receipt split over two accounts can come back a row short, like an invoice; the total check said "Add line"
  // on it, but there was no Add line.
  assert.equal(takesLines(tx({ document_type: 'receipt', document_total: '17.99' })), true)
  assert.equal(takesLines(tx({ document_type: 'receipt', document_total: null })), false)
  assert.equal(takesLines(tx({ document_type: 'invoice', document_total: null })), true)
  assert.equal(takesLines(tx({ document_type: 'statement', document_total: '17.99' })), false)
  assert.equal(takesLines(tx({ document_type: 'receipt', document_total: '17.99', document_ref: null })), false)
})

test('the date another record shows is used with one click', () => {
  // The Southgate receipt was read as 9 August; Jenny's claim line for it says 9 September.
  const receipt = tx({ document_type: 'receipt', owed: null, date: '2026-08-09', date_found: '2026-09-09' })
  assert.deepEqual(rowStatus(receipt).at(-1), { text: 'Which date is right?',
                                                actions: [{ label: 'Use 9 Sep 2026', change: { date: '2026-09-09' } }] })
  assert.equal(rowStatus({ ...receipt, date_found: null }).length, 0)
})

test('a warning about this row and another offers Show both; one about this row alone does not', () => {
  // A possible duplicate named the other row, but finding it meant going through every transaction.
  for (const code of ['possible_duplicate', 'date_conflict', 'amount_conflict', 'booked_twice', 'total_mismatch']) {
    assert.equal(aboutAnotherRow(code), true, code)
  }
  for (const code of ['vat_rate_mismatch', 'mixed_items']) assert.equal(aboutAnotherRow(code), false, code)
  assert.deepEqual([showLabel('possible_duplicate'), showLabel('total_mismatch')], ['Show both', 'Show its lines'])
})

test('two records can be said not to be the same, and the decision undone', () => {
  // Not the same is offered where two records may be one; a line booked twice is unticked instead.
  for (const code of ['possible_duplicate', 'date_conflict', 'amount_conflict']) assert.equal(canBeApart(code), true, code)
  for (const code of ['booked_twice', 'total_mismatch']) assert.equal(canBeApart(code), false, code)
  const row = { ...tx(), apart_from: [3] }
  assert.deepEqual(apartChange(row, [4, 3]), { apart_from: [3, 4] })
  const names = new Map([[3, 'EE monthly phone charges'], [4, 'M6toll toll charge']])
  assert.deepEqual(apartStatus({ ...row, apart_from: [3, 9] }, id => names.get(id)),
                   { text: 'Not the same as "EE monthly phone charges" (you said)', actions: [{ label: 'Undo', change: { apart_from: [] } }] })
  assert.equal(apartStatus({ ...row, apart_from: [9] }, id => names.get(id)), null)   // the other row is gone
  assert.equal(apartStatus(tx(), id => names.get(id)), null)
})

test('the amount another record shows is used with one click', () => {
  // Matt's M6 toll receipt was read as £14.00; his claim line for it says £12.00.
  const receipt = tx({ document_type: 'receipt', owed: null, gross: '14.00', amount_found: '12.00' })
  assert.deepEqual(rowStatus(receipt).at(-1), { text: 'Which amount is right?',
                                                actions: [{ label: 'Use £12.00', change: { gross: '12.00' } }] })
  assert.equal(rowStatus({ ...receipt, amount_found: null }).length, 0)
})

test('a pair asking which amount is right offers both amounts, each setting the other record to match', () => {
  // Matt's EE bill of £30.22 and his claim line of £27.50: only one of the two answers was on offer.
  const asks = (other: number) => [{ code: 'amount_conflict', severity: 'warning' as const, message: '', related: [other] }]
  const line = tx({ document_type: 'expense_claim', gross: '27.50', amount_found: '30.22', issues: asks(6) })
  const bill = tx({ document_type: 'invoice', gross: '30.22', amount_found: '27.50', issues: asks(5), owed: null,
                    recorded_by: { ref: 'claim', amount: '27.50', date: '2026-09-03', description: 'Matt Barnes — EE',
                                   kind: 'expense_claim' } })
  const rows = new Map([[5, line], [6, bill]])
  assert.deepEqual(rowStatus(bill, id => rows.get(id)), [
    { text: 'Not booked while the amounts differ: Matt Barnes — EE (£27.50, 3 Sept) is booked meanwhile', actions: [] },
    { text: 'Which amount is right?', actions: [{ label: '£27.50 (the claim)', change: { gross: '27.50' } },
                                                 { label: '£30.22 (the invoice)', change: { gross: '30.22' }, row: 5 }] },
  ])
  assert.deepEqual(rowStatus(line, id => rows.get(id)).at(-1)?.actions.map(a => a.label),   // the same order on both rows
                   ['£27.50 (the claim)', '£30.22 (the invoice)'])
  // Against a bank line only the bank's amount is offered: the bank line does not ask.
  const card = tx({ document_type: 'statement', gross: '12.00' })
  const toll = tx({ document_type: 'receipt', gross: '14.00', amount_found: '12.00', issues: asks(7), owed: null })
  assert.deepEqual(rowStatus(toll, id => new Map([[7, card]]).get(id)).at(-1),
                   { text: 'Which amount is right?', actions: [{ label: '£12.00 (the bank)', change: { gross: '12.00' } }] })
})

test('the Check column hover names the warnings, once each', () => {
  // It repeated every warning in full, which the Description column already shows.
  const issue = (code: string) => ({ code, severity: 'warning' as const, message: 'long text' })
  assert.equal(checkHover([issue('amount_conflict'), issue('booked_twice'), issue('amount_conflict')]),
               'Which amount?, Booked twice')
  assert.equal(checkHover([]), 'No issues')
})

test('the Account column shows the account name only, never its code', () => {
  assert.equal(accountName(tx({ account_code: '7402', account_name: 'Hotels' })), 'Hotels')
  assert.equal(accountName(tx({ paid_against: '2100', paid_against_name: 'Creditors' })), 'Creditors')
  assert.equal(accountName(tx({ account_code: '9999', account_name: null })), 'Unknown account')   // not in the chart
})

test('VAT a receipt shows only in its prices is booked with one click once the VAT invoice is in', () => {
  // The Amazon receipt says it is not a VAT invoice; the claim and its prices agree the VAT is £3.00.
  const receipt = tx({ document_type: 'receipt', gross: '17.99', vat: null, vat_posted: '0.00', net: '17.99', owed: null,
                       vat_found: '3.00', claimed_in: { ref: 'claim', amount: '17.99', date: '2026-09-11',
                                                        description: "Jenny Hogg's expense claim", kind: 'expense_claim' } })
  const [, book] = rowStatus(receipt)
  assert.deepEqual(book, { text: 'VAT £3.00 not booked until you have the VAT invoice',
                           actions: [{ label: 'Book VAT £3.00', change: { vat: '3.00' } }] })
  assert.equal(rowStatus({ ...receipt, vat_found: null }).length, 1)
})

test('issues are named, and the review summary counts each kind once per row', () => {
  const missing = { code: 'total_mismatch', severity: 'warning' as const, message: '£54.00 is missing.' }
  const note = { code: 'vat_blocked', severity: 'info' as const, message: "VAT can't be reclaimed." }
  assert.equal(issueTitle('total_mismatch'), "Total doesn't add up")
  assert.equal(issueTitle('something_new'), 'Check this')
  // A heading is its title as a sentence: "Which amount?." read badly.
  assert.deepEqual([issueHeading('total_mismatch'), issueHeading('amount_conflict')],
                   ["Total doesn't add up.", 'Which amount?'])
  for (const code of ['vat_worked_out', 'not_vat_invoice', 'date_conflict', 'file_date', 'date_from_claim',
                      'date_from_bank', 'booked_twice', 'amount_conflict']) assert.notEqual(issueTitle(code), 'Check this', code)
  assert.deepEqual(reviewSummary([[missing, missing], [missing], [note], []]), [
    { code: 'total_mismatch', title: "Total doesn't add up", severity: 'warning', rows: 2 },
  ])
})

test("a receipt already on an expense claim is not a duplicate of the claim's other lines", () => {
  // The 11 Sep Amazon receipt is on Jenny's claim; it was flagged as repeating the 8 Sep line of the same item.
  const earlier = { ...tx({ document_type: 'expense_claim', document_ref: 'claim', gross: '17.99', date: '2026-09-08' }), upload_id: 1 }
  const receipt = { ...tx({ document_type: 'receipt', document_ref: 'r', gross: '17.99', date: '2026-09-11', owed: null,
                            claimed_in: { ref: 'claim', amount: '17.99', date: '2026-09-11', description: 'claim' } }),
                    upload_id: 2 }
  assert.deepEqual(possibleDuplicates([paymentRowOf(earlier), paymentRowOf(receipt)]), [null, null])
})
