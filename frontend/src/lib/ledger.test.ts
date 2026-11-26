// Run with: npm test (Node's own test runner; Node strips the TypeScript types itself).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import type { Transaction } from './api.ts'
import { capActions, filterChips, filtersSet, keepSelected, levelsLine, matchesFilters, needsReviewLabel, netBooked, NO_FILTERS, pageOf, pageReaching, ROWS_PER_PAGE, rowHeadline, signedAmount, tableDate, vatBooked } from './ledger.ts'
import { aboutAnotherRow, acceptChange, acceptLabel, accountName, askAbout, claimLineOf, issueFixes, apartChange, apartStatus, canBeAccepted, canBeApart, checkHover, issueHeading, issueTitle, kindOf, needsReview, postedLedgerNote,
         reviewSummary, rowStatus, showLabel, takesLines, totalsOf } from './ledger.ts'

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
  assert.deepEqual(rowStatus(receipt).map(s => s.text), ['Paid from the bank: line on 23 Feb'])
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
  // what the books hold now: a row waiting for its document is in Suspense, and a line its receipt books posts nothing
  const held = [{ code: 'needs_document', severity: 'warning' as const, message: 'Held in Suspense: needs its receipt or invoice.' }]
  assert.equal(accountName(tx({ account_code: '7500', account_name: 'Printing', issues: held })), 'Suspense, then Printing')
  assert.equal(accountName(tx({ account_code: '9998', account_name: 'Suspense', issues: held })), 'Suspense')
  assert.equal(accountName(tx({ account_code: '9998', account_name: 'Suspense',
                                recorded_by: { ref: 'r', amount: '58.00', date: null, description: 'Costco', kind: 'receipt' } })),
               'Booked from its document')
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
                      'date_from_bank', 'booked_twice', 'amount_conflict', 'claimed_less', 'no_payroll', 'wages_from_bank', 'payroll_owed_to', 'vat_not_booked', 'needs_document', 'total_worked_out', 'cis_deducted', 'payout_report', 'personal', 'subtotal_only']) assert.notEqual(issueTitle(code), 'Check this', code)
  assert.deepEqual(reviewSummary([[missing, missing], [missing], [note], []]), [
    { code: 'total_mismatch', title: "Total doesn't add up", severity: 'warning', rows: 2 },
  ])
})

test('a row left out of the books or replaced by a split is not in the totals', () => {
  // The agent left out the sheet line repeating a £42 receipt, but Paid out (bank) still said £84.00 for 2.
  const receipt = tx({ document_type: 'receipt', document_ref: 'r', gross: '42.00', vat_posted: '7.00', net: '35.00',
                       owed: null })
  const bill = tx()
  for (const out of [{ excluded: true }, { superseded_by: 'decision' }]) {
    assert.deepEqual(totalsOf([receipt, { ...receipt, document_ref: 's', ...out }]).map(t => [t.label, t.count, t.gross]),
                     [['Paid out (bank)', 1, '42.00']])
    // A copy of a bill left out is not owed a second time.
    assert.deepEqual(totalsOf([bill, { ...bill, document_ref: 'copy', ...out }]).map(t => [t.count, t.gross, t.stillOwed]),
                     [[1, '12000.00', '12000.00']])
  }
})

test('the posted ledger is noted only when it is not up to date', () => {
  assert.equal(postedLedgerNote(0), null)
  assert.equal(postedLedgerNote(null), null)
  assert.equal(postedLedgerNote(1), 'Not up to date: 1 change not posted. See Trial balance.')
  assert.equal(postedLedgerNote(2), 'Not up to date: 2 changes not posted. See Trial balance.')
})

test('a row left out of the books or replaced by a split needs no review, whatever is wrong with it', () => {
  // A duplicate a decision dropped kept its error, and the table still counted it as one to review.
  const wrong = { issues: [{ code: 'unknown_account', severity: 'error' as const, message: "This account isn't in the chart." }] }
  assert.deepEqual([tx(wrong), tx({ ...wrong, excluded: true }), tx({ ...wrong, superseded_by: 'decision' })].map(t => needsReview(t)),
                   [true, false, false])
  // The issues the page adds itself, such as a possible duplicate, count as the row's own do; a note never does.
  const duplicate = [{ code: 'possible_duplicate', severity: 'warning' as const, message: 'Same amount' }]
  assert.deepEqual([needsReview(tx(), duplicate), needsReview(tx({ excluded: true }), duplicate)], [true, false])
  assert.equal(needsReview(tx({ issues: [{ code: 'unusual_direction', severity: 'info', message: 'A refund?' }] })), false)
})

test('a purchase booked without its receipt says why, with a way to hold it for the receipt again', () => {
  const booked = tx({ document_type: 'statement', without_document: 'Receipt lost',
                      issues: [{ code: 'booked_without_document', severity: 'info', message: 'Booked without a receipt: Receipt lost; no VAT reclaimed.' }] })
  const [line] = rowStatus(booked).filter(s => s.text.startsWith('Booked without a receipt'))
  assert.equal(line.text, 'Booked without a receipt: Receipt lost. No VAT reclaimed')
  assert.deepEqual(line.actions, [{ label: 'Hold for the receipt instead', change: { without_document: null } }])
  // A reason the rules don't need (the row books anyway) shows nothing.
  assert.deepEqual(rowStatus(tx({ document_type: 'statement', without_document: 'Lost' }))
    .filter(s => s.text.startsWith('Booked without')), [])
})

test('the claim and sundry questions are named, and can be marked as fine', () => {
  assert.equal(issueTitle('sundry_check'), 'Sundry: what was it for?')
  assert.equal(issueTitle('claim_note'), 'Coded by the claim')
  assert.equal(canBeAccepted('sundry_check'), true)
})

test("a judgement warning can be marked as fine, and a hard error can't", () => {
  assert.equal(canBeAccepted('no_vat_number'), true)
  assert.equal(canBeAccepted('addressed_to'), true)
  assert.equal(canBeAccepted('vat_arithmetic'), false)
  assert.deepEqual(acceptChange(tx({ accepted: ['small_asset'] }), 'meal_check'), { accepted: ['small_asset', 'meal_check'] })
  assert.equal(issueTitle('no_vat_number'), 'No VAT number on the invoice')
})

// ─── Fixing an issue from where it is listed ─────────────────────────────────

const warning = (code: string, message = '') => ({ code, message, severity: 'warning' as const, related: [] })
const claim = { ref: 'claim', amount: '12.00', date: '2026-09-14', description: "Matt Barnes's expense claim", kind: 'expense_claim' }
const toll = tx({ document_type: 'receipt', document_ref: 'toll', account_code: '9998', account_name: 'Suspense',
                  gross: '12.00', vat: '2.00', claimed_in: claim, description: 'M6toll' })
const tollLine = tx({ document_type: 'expense_claim', document_ref: 'claim', account_code: '7400', account_name: 'Travel',
                      gross: '12.00', vat: '2.00', recorded_by: { ref: 'toll', amount: '12.00', date: '2026-09-14', description: 'M6toll', kind: 'receipt' } })

test('a receipt on a claim finds its claim line, and no other row does', () => {
  assert.equal(claimLineOf(toll, [tx(), tollLine, toll]), tollLine)
  assert.equal(claimLineOf(tx(), [tx(), tollLine, toll]), undefined)
})

test('a row in Suspense offers the account its claim has, and the list of accounts', () => {
  assert.deepEqual(issueFixes(toll, warning('account_unclear'), tollLine), [
    { label: 'Use Travel, as the claim has it', change: { account_code: '7400' } },
    { label: 'Choose the account', choose: 'account' }])
  assert.deepEqual(issueFixes(toll, warning('account_unclear')), [{ label: 'Choose the account', choose: 'account' }])
  // the VAT ignored on Suspense goes with the account: nothing of its own to do
  assert.deepEqual(issueFixes(toll, warning('vat_not_applicable')), [])
  assert.deepEqual(issueFixes(tx({ account_code: '2100' }), warning('vat_not_applicable')), [{ label: 'Remove the VAT', change: { vat: null } }])
})

test('VAT only the claim shows can be booked as claimed, or left out', () => {
  const hotelLine = { ...tollLine, vat: '384.75' }
  assert.deepEqual(issueFixes(toll, warning('claim_vat'), hotelLine), [{ label: 'Book VAT £384.75, as claimed', change: { vat: '384.75' } }])
  assert.equal(canBeAccepted('claim_vat'), true)
  assert.equal(acceptLabel('claim_vat'), "It's fine")
  assert.equal(acceptLabel('document_wanted'), "It's fine without one")
  // booked as the claim shows it already: the way out is to say it carries none
  assert.deepEqual(issueFixes({ ...toll, vat_from_claim: true }, warning('claim_vat'), hotelLine), [{ label: 'No VAT on it', change: { vat: '0.00' } }])
  assert.deepEqual(issueFixes(tx(), warning('document_wanted')), [{ label: 'Add the document', documents: true }])
})

test("a UK hotel stay booked with its VAT asks for the property's invoice, or takes the VAT off", () => {
  assert.equal(issueHeading('hotel_vat'), 'Invoice needed.')
  assert.deepEqual(issueFixes(tx(), warning('hotel_vat')),
                   [{ label: 'Add the document', documents: true }, { label: 'No VAT on it', change: { vat: '0.00' } }])
  assert.equal(canBeAccepted('hotel_vat'), true)
  assert.equal(acceptLabel('hotel_vat'), "It's fine without one")
})

test('a date, a currency, VAT and a missing document each say where they are fixed; a note offers nothing', () => {
  assert.deepEqual(issueFixes(tx(), warning('date_missing')), [{ label: 'Set the date', edit: true }])
  assert.deepEqual(issueFixes(tx(), { ...warning('non_gbp_currency'), severity: 'error' }), [{ label: 'Enter it in pounds', edit: true }])
  assert.deepEqual(issueFixes(tx(), warning('vat_arithmetic')), [{ label: 'Correct the VAT', edit: true }])
  assert.deepEqual(issueFixes(tx(), warning('needs_document')), [{ label: 'Add the document', documents: true }])
  assert.deepEqual(issueFixes(tx(), { ...warning('account_unclear'), severity: 'info' }), [])
  assert.deepEqual(issueFixes(tx(), warning('possible_duplicate')), [])   // Show both and Not the same are its controls
})

test('asking the AI about an issue names the row and what is wrong with it', () => {
  assert.equal(askAbout(toll, warning('account_unclear', 'Account unclear: put in Suspense. Choose one.')),
    'Help me fix this: "M6toll", 1 Oct 2026, £12.00. Account to check. Account unclear: put in Suspense. Choose one. '
    + 'Tell me the options, and make the change when I say which.')
})

// ─── VAT the books don't reclaim ─────────────────────────────────────────────

test('a row whose VAT is not reclaimed shows no VAT and its whole amount, as the trial balance holds it', () => {
  const held = tx({ gross: '547.84', vat: '91.31', vat_posted: '91.31', net: '456.53', vat_not_reclaimed: '91.31',
                    document_type: 'statement' })
  assert.deepEqual([vatBooked(held), netBooked(held)], ['0.00', '547.84'])
  const booked = tx({ gross: '9.72', vat: '1.62', vat_posted: '1.62', net: '8.10', document_type: 'statement' })
  assert.deepEqual([vatBooked(booked), netBooked(booked)], ['1.62', '8.10'])
  const [total] = totalsOf([held, booked])
  assert.deepEqual([total.gross, total.vat, total.net], ['557.56', '1.62', '555.94'])
})

test('VAT the books hold back can be reclaimed on the person\'s say, and that can be taken back', () => {
  const held = tx({ document_type: 'receipt', gross: '547.84', vat: '91.31', vat_posted: '91.31', net: '456.53', vat_not_reclaimed: '91.31' })
  assert.deepEqual(issueFixes(held, warning('needs_document')), [
    { label: 'Reclaim VAT £91.31 and book it', change: { vat_confirmed: true } },
    { label: 'No VAT on it', change: { vat: '0.00' } },
    { label: 'Add the document', documents: true }])
  assert.deepEqual(issueFixes(tx(), warning('needs_document')), [{ label: 'Add the document', documents: true }])
  assert.deepEqual(issueFixes(held, { ...warning('vat_confirmed'), severity: 'info' }), [{ label: "Don't reclaim it", change: { vat_confirmed: false } }])
  assert.equal(issueTitle('vat_confirmed'), 'VAT reclaimed on your say')
})

test('VAT worked out of the amount can be set to none, or entered', () => {
  assert.deepEqual(issueFixes(tx(), { ...warning('vat_implied'), severity: 'info' }),
                   [{ label: 'No VAT on it', change: { vat: '0.00' } }, { label: 'Enter the VAT', edit: true }])
})

// ─── Filtering the table ─────────────────────────────────────────────────────

test('a row must pass every filter that is set, and an empty filter passes everything', () => {
  const hotel = tx({ description: 'Booking.com, hotel stay', counterparty: 'Booking.com', account_code: '7402', account_name: 'Hotels',
                     gross: '255.98', vat_posted: '42.66', date: '2026-10-26', document_type: 'receipt', direction: 'out' })
  const f = (change: Partial<typeof NO_FILTERS>) => ({ ...NO_FILTERS, ...change })
  assert.equal(matchesFilters(hotel, NO_FILTERS), true)
  assert.equal(filtersSet(NO_FILTERS), 0)
  assert.equal(filtersSet(f({ text: 'hotel', min: '100' })), 2)
  // words: each must be found, in the description, who was paid, the account or the file
  assert.equal(matchesFilters(hotel, f({ text: 'booking HOTEL' })), true)
  assert.equal(matchesFilters(hotel, f({ text: 'booking flight' })), false)
  assert.equal(matchesFilters(hotel, f({ text: 'spitalfields' }), 'Booking.com-Spitalfields.pdf'), true)
  assert.equal(matchesFilters(hotel, f({ text: 'hotels' })), true)
  // each field narrows, and they narrow together
  assert.equal(matchesFilters(hotel, f({ account: '7402', type: 'receipt', direction: 'out' })), true)
  assert.equal(matchesFilters(hotel, f({ account: '7400' })), false)
  assert.equal(matchesFilters(hotel, f({ type: 'invoice' })), false)
  assert.equal(matchesFilters(hotel, f({ direction: 'in' })), false)
  assert.equal(matchesFilters(hotel, f({ from: '2026-10-26', to: '2026-10-26' })), true)
  assert.equal(matchesFilters(hotel, f({ from: '2026-10-27' })), false)
  assert.equal(matchesFilters(tx({ date: null }), f({ to: '2026-12-31' })), false)
  assert.equal(matchesFilters(hotel, f({ min: '255.98', max: '255.98' })), true)
  assert.equal(matchesFilters(hotel, f({ min: '300' })), false)
  assert.equal(matchesFilters(hotel, f({ max: 'abc' })), true)
  assert.equal(matchesFilters(hotel, f({ account: '7402', min: '300' })), false)
  // what state it is in
  assert.equal(matchesFilters(hotel, f({ status: 'vat' })), true)
  assert.equal(matchesFilters({ ...hotel, vat_not_reclaimed: '42.66' }, f({ status: 'vat' })), false)
  assert.equal(matchesFilters(hotel, f({ status: 'no_vat' })), false)
  assert.equal(matchesFilters(hotel, f({ status: 'review' })), false)
  assert.equal(matchesFilters({ ...hotel, issues: [warning('document_wanted')] }, f({ status: 'review' })), true)
  assert.equal(matchesFilters({ ...hotel, edited: true }, f({ status: 'edited' })), true)
  assert.equal(matchesFilters(hotel, f({ status: 'edited' })), false)
})

// ─── A document's problem, a removed row, and a total left as it is ──────────────────────────────────────────────

import type { SavedRow, Upload } from './clients'
import { documentProblems, leftOutLabel, linkedRows, removedForGood, rowIssues } from './ledger.ts'

const saved = (id: number, change: Partial<Transaction> = {}): SavedRow =>
  ({ ...tx({ document_type: 'expense_claim', document_ref: 'claim', ...change }), id, upload_id: 1 } as unknown as SavedRow)
const short = { code: 'total_mismatch', severity: 'warning' as const, message: '£457.20 missing: add the line.',
                related: [2], about: 'document' as const, difference: '457.20' }

test("a document's problem is not one of its first line's own issues", () => {
  const own = { code: 'date_missing', severity: 'warning' as const, message: 'No date' }
  const rowOnly = { ...short, about: 'row' as const }
  assert.deepEqual(rowIssues(tx({ issues: [short, own, rowOnly] })), [own, rowOnly])
  // so the line is not marked for review on the document's account (rows saved before `about` read as the row's)
  assert.equal(needsReview(tx({ issues: [short] }), rowIssues(tx({ issues: [short] }))), false)
})

test("a document's problem is listed once, with every line of the document that is in the books", () => {
  const rows = [saved(1, { issues: [short] }), saved(2), saved(3, { excluded: true }), saved(4, { document_ref: 'other' })]
  const [found, ...rest] = documentProblems(rows)
  assert.deepEqual([found.row.id, found.issue, found.lines, rest.length], [1, short, [1, 2], 0])
  // a note about a document is not a problem, and a left-out row's problem no longer matters
  assert.deepEqual(documentProblems([saved(1, { issues: [{ ...short, severity: 'info' }] })]), [])
  assert.deepEqual(documentProblems([saved(1, { issues: [short], excluded: true })]), [])
})

test('a row out of the books says who took it out', () => {
  assert.deepEqual([tx({ superseded_by: 'd1' }), tx({ excluded: true, removed: true }), tx({ excluded: true })].map(leftOutLabel),
                   ['Replaced', 'Removed by you', 'Left out'])
})

test('only a row typed in by hand is removed for good', () => {
  const uploads = [{ id: 1, kind: 'pdf' }, { id: 2, kind: 'manual' }] as Upload[]
  assert.equal(removedForGood(saved(1), uploads), false)
  assert.equal(removedForGood({ ...saved(2), upload_id: 2 }, uploads), true)
})

test('a total that does not add up can be left as it is, and that can be undone', () => {
  assert.deepEqual(issueFixes(tx(), short), [{ label: 'Leave it as it is', change: { total_accepted: '457.20' } }])
  assert.deepEqual(issueFixes(tx(), { ...short, difference: null }), [])   // read before the difference was kept
  const note = { code: 'total_accepted', severity: 'info' as const, message: "Lines total £1,148.43, £457.20 under the claim's £1,605.63." }
  assert.deepEqual(issueFixes(tx(), note), [{ label: 'Undo', change: { total_accepted: null } }])
  assert.equal(issueHeading('total_accepted'), 'Total left as it is.')
})

// Jenny's TfL claim line is booked from seven charges on her TfL statement; the eighth is left off the claim.
const tflSet = { ref: 'tfl-06', amount: '55.40', date: '2026-10-27', kind: 'receipt',
                 description: 'TfL Customer Services, 7 charges, 6 to 27 Oct 2026' }
const tflLine = (change: Partial<Transaction> = {}) => tx({
  document_type: 'expense_claim', document_ref: 'claim', description: 'Jenny Hogg - Transport for London, Train',
  gross: '55.40', owed: null, recorded_by: tflSet, recorded_by_refs: ['tfl-06', 'tfl-07', 'tfl-08', 'tfl-10', 'tfl-20',
                                                                     'tfl-21', 'tfl-27'], ...change,
})

test('a claim line booked from several receipts says how many, and can be ticked to book it as well', () => {
  const [unticked] = rowStatus(tflLine())
  assert.ok(unticked.text.startsWith('Booked from 7 receipts: TfL Customer Services, 7 charges'))
  assert.ok(unticked.text.endsWith('Tick to book this line as well'))
  assert.equal(kindOf(tflLine()), 'not booked')
  const [ticked] = rowStatus(tflLine({ include: true }))
  assert.ok(ticked.text.startsWith('Booked as well as 7 receipts: TfL Customer Services'))
  assert.ok(ticked.text.endsWith('Untick to book it from the receipts only'))
})

test('a receipt finds its claim line among the receipts the line is booked from', () => {
  const claim = { ref: 'claim', amount: '55.40', date: '2026-10-31', kind: 'expense_claim',
                  description: "Jenny Hogg's expense claim" }
  const receipt = tx({ document_type: 'receipt', document_ref: 'tfl-20', claimed_in: claim, gross: '6.60' })
  assert.equal(claimLineOf(receipt, [tflLine(), receipt])?.document_ref, 'claim')
})

test('a charge the claim leaves out is not booked until ticked, and says so', () => {
  const left = { ref: 'claim', amount: '55.40', date: '2026-10-31', kind: 'expense_claim',
                 description: "Jenny Hogg's expense claim" }
  const row = tx({ document_type: 'receipt', document_ref: 'tfl-05', gross: '6.10', owed: null, left_off_claim: left })
  assert.equal(kindOf(row), 'not booked')
  const [status] = rowStatus(row)
  assert.equal(status.text, "Not on Jenny Hogg's expense claim, not booked. Tick to include it")
  assert.equal(status.include, false)
  assert.notEqual(kindOf({ ...row, include: true }), 'not booked')
})

test('the issues about several receipts on one claim line have titles', () => {
  assert.equal(issueTitle('not_claimed'), 'Not claimed')
  assert.equal(issueTitle('claim_receipts_unclear'), "Can't tell which charges")
  assert.ok(aboutAnotherRow('claim_receipts_unclear'))
})

test('the questions asked by facts and stakes are named, and the materiality is said in a line', () => {
  assert.equal(issueTitle('account_fact'), 'Which account?')
  assert.equal(issueTitle('account_choice'), 'Another account?')
  assert.equal(issueTitle('left_small'), 'Left: under the trivial level')
  assert.equal(issueTitle('left_unset'), 'Left: materiality not set')
  assert.equal(issueTitle('meal_decided'), 'Who was there: settled')
  assert.equal(issueTitle('small_items_add_up'), 'Small items add up')
  for (const code of ['account_fact', 'account_choice', 'small_items_add_up']) assert.equal(canBeAccepted(code), true)
  assert.equal(levelsLine({ overall: '1500.00', working: '750.00', trivial: '45.00', benchmark: 'profit',
                            figure: '30000.00', basis: '5% of profit before tax, £30,000.00, last year' }),
               'Materiality £1,500.00 (5% of profit before tax, £30,000.00, last year) · items under £45.00 left as coded')
  assert.equal(levelsLine(null), "Materiality not set: no sales booked and no earlier year to work it out from. Set it "
                                 + "in the client's details; until then, questions where either account is right wait. "
                                 + 'Questions that change the tax are asked now.')
})

test('the table draws a page of rows at a time and says how many more there are', () => {
  // The website: the Transactions tab drew all 1,351 of the agency's rows at once.
  const rows = Array.from({ length: 1351 }, (_, k) => k)
  assert.equal(ROWS_PER_PAGE, 200)
  assert.deepEqual([pageOf(rows, 200).shown.length, pageOf(rows, 200).more], [200, 1151])
  assert.deepEqual([pageOf(rows, 1400).shown.length, pageOf(rows, 1400).more], [1351, 0])
  assert.deepEqual(pageOf(rows, 400).shown.slice(-1), [399])
})

// ─── The compact table (one queue, clean ledger) ─────────────────────────────

const flag = (code: string, severity: 'info' | 'warning' | 'error' = 'warning') => ({ code, severity, message: `${code} said` })

test('the table date is day, short month and two-digit year', () => {
  assert.equal(tableDate('2023-04-01'), '01 Apr 23')
  assert.equal(tableDate(null), '—')
})

test('money in is signed + and money out −; a journal has no sign', () => {
  assert.deepEqual(signedAmount(tx({ direction: 'in', gross: '4800.00' })), { text: '+4,800.00', tone: 'in' })
  assert.deepEqual(signedAmount(tx({ direction: 'out', gross: '504' })), { text: '−504.00', tone: 'out' })
  assert.deepEqual(signedAmount(tx({ document_type: 'journal', gross: '2400' })), { text: '2,400.00', tone: 'plain' })
})

test('a flagged row is headed by its worst issue, with +N for the rest', () => {
  const h = rowHeadline(tx(), [flag('payout_report'), flag('non_gbp_currency', 'error'), flag('possible_duplicate')])
  assert.deepEqual(h, { text: 'Not in pounds · +2', severity: 'error' })
})

test("a document's problem heads each of its lines when the line has none worse", () => {
  assert.deepEqual(rowHeadline(tx(), [], flag('total_mismatch')), { text: "Total doesn't add up", severity: 'warning' })
  assert.deepEqual(rowHeadline(tx(), [flag('non_gbp_currency', 'error')], flag('total_mismatch')),
                   { text: 'Not in pounds · +1', severity: 'error' })
})

test('a row with nothing wrong is headed by its type and first status; notes do not head it', () => {
  assert.deepEqual(rowHeadline(tx({ owed: '0.00', paid_by: paidBy }), [flag('reverse_charge', 'info')]),
                   { text: 'Invoice · paid 3 Oct', severity: null })
  assert.deepEqual(rowHeadline(tx(), []), { text: 'Invoice · Unpaid, owed to Business Cube', severity: null })
})

test('a left-out row is headed left out, never flagged', () => {
  assert.deepEqual(rowHeadline(tx({ excluded: true }), [flag('non_gbp_currency', 'error')]), { text: 'left out', severity: null })
})

test('more than three candidates: three shown, the rest in a picker', () => {
  const acts = [1, 2, 3, 4, 5].map(n => ({ label: `Link ${n}`, change: { link: [`b${n}`] } }))
  const { shown, rest } = capActions(acts)
  assert.deepEqual(shown.map(a => a.label), ['Link 1', 'Link 2', 'Link 3'])
  assert.deepEqual(rest.map(a => a.label), ['Link 4', 'Link 5'])
  assert.equal(capActions(acts.slice(0, 3)).rest.length, 0)
})

test('each filter set is one chip; the two dates and the two amounts are one chip each', () => {
  const names = { account: (code: string) => (code === '7100' ? 'Rent' : code), type: (t: string) => (t === 'invoice' ? 'Invoice' : t) }
  const chips = filterChips({ ...NO_FILTERS, direction: 'out', from: '2023-04-01', to: '2023-06-30', min: '100' }, names)
  assert.deepEqual(chips.map(c => c.label), ['Money out', '01 Apr 23 – 30 Jun 23', 'From £100.00'])
  assert.deepEqual(chips.map(c => c.field), ['direction', 'dates', 'amounts'])
  const more = filterChips({ ...NO_FILTERS, text: 'stripe', account: '7100', type: 'invoice', status: 'review', to: '2023-06-30', max: '50' }, names)
  assert.deepEqual(more.map(c => c.label), ['“stripe”', 'Rent', 'Invoice', 'To review', 'Until 30 Jun 23', 'Up to £50.00'])
})

test('only the links are capped: "None of these" stays a button', () => {
  // Final review I1: "None of these" was the last option of the "Link to another…" picker.
  const links = [1, 2, 3, 4, 5].map(n => ({ label: `Link ${n}`, change: { link: [`b${n}`] } }))
  const none = { label: 'None of these', change: { link: [] } }
  const { shown, rest } = capActions([...links, none])
  assert.deepEqual(shown.map(a => a.label), ['Link 1', 'Link 2', 'Link 3', 'None of these'])
  assert.deepEqual(rest.map(a => a.label), ['Link 4', 'Link 5'])
  assert.equal(capActions([...links.slice(0, 3), none]).rest.length, 0)
})

test('a left-out row says why, when the decision that left it out gives a reason', () => {
  assert.deepEqual(rowHeadline(tx({ excluded: true }), [], null, 'Repeats the receipt already booked'),
                   { text: 'left out · Repeats the receipt already booked', severity: null })
  assert.deepEqual(rowHeadline(tx({ excluded: true }), [], null, null), { text: 'left out', severity: null })
})

test('the table pages far enough to show the open row', () => {
  const ids = Array.from({ length: 450 }, (_, n) => n + 1)
  assert.equal(pageReaching(ids, 5, ROWS_PER_PAGE), ROWS_PER_PAGE)
  assert.equal(pageReaching(ids, 201, ROWS_PER_PAGE), 2 * ROWS_PER_PAGE)
  assert.equal(pageReaching(ids, 450, ROWS_PER_PAGE), 3 * ROWS_PER_PAGE)
  assert.equal(pageReaching(ids, 999, ROWS_PER_PAGE), ROWS_PER_PAGE)   // not listed: as it was
  assert.equal(pageReaching(ids, null, 2 * ROWS_PER_PAGE), 2 * ROWS_PER_PAGE)
})

test('showing rows together keeps the open row when it is one of them', () => {
  assert.equal(keepSelected(7, [3, 7, 9]), 7)
  assert.equal(keepSelected(4, [3, 7, 9]), 3)
  assert.equal(keepSelected(null, [3, 7]), 3)
  assert.equal(keepSelected(4, []), null)
})

test('the review count names rows and documents apart', () => {
  assert.equal(needsReviewLabel(110, 6), 'Needs review · 110 rows, 6 documents')
  assert.equal(needsReviewLabel(1, 1), 'Needs review · 1 row, 1 document')
  assert.equal(needsReviewLabel(1355, 0), 'Needs review · 1,355 rows')
  assert.equal(needsReviewLabel(0, 2), 'Needs review · 2 documents')
})

test("a link to a row opens it beside the rows its issues name; one to a document, beside every line of it", () => {
  const rows = [saved(1, { issues: [short] }), saved(2), saved(3, { excluded: true }),
                saved(4, { document_ref: 'other', issues: [{ code: 'possible_duplicate', severity: 'warning', message: '', related: [9] }] })]
  assert.deepEqual(linkedRows(rows, 1, true), [1, 2])
  assert.deepEqual(linkedRows(rows, 4, false), [4, 9])
  assert.deepEqual(linkedRows(rows, 4, true), [4])      // no problem of its document's: the row alone
  assert.equal(linkedRows(rows, 77, false), undefined)
})

test('the who-was-it-for question fits a shop as well as a meal', () => {
  // Groceries the company paid for ask whose they were (25 Nov 2026): "who was there" reads oddly for a shop.
  assert.equal(issueTitle('meal_check'), 'Who was it for?')
})

test('a subscription a media business keeps as a cost has a title of its own', () => {
  // What the business does decides a streaming subscription (26 Nov 2026).
  assert.equal(issueTitle('for_the_trade'), 'Kept for the business')
})
