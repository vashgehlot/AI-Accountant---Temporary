// Run with: npm test (Node's own test runner; Node strips the TypeScript types itself).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import type { Transaction } from './api.ts'
import type { ClientSummary, SavedRow, Upload } from './clients.ts'
import type { PickedFile, ReadingFile } from './clientRules.ts'
import {
  accountList, bankAccountsLeft, changesOf, ownerError, ownersToSend, clientFormErrors, dayMonth, draftOf, emptyListText, figuresOf, lineTemplate, newRowFrom, paidFromOf, paidFromOptions, requeue,
  readingLine, removeUploadsText, rowEditErrors, sameFileAs, searchClients, someFinished, unsent, showsInvitation, statementText, transactionCount,
  vatWorkedOut,
} from './clientRules.ts'

const client = (change: Partial<ClientSummary> = {}): ClientSummary => ({
  id: 1, name: 'Business Cube Ltd', business_type: 'limited_company', contact_name: 'Jenny Clarke',
  contact_email: 'jenny@businesscube.co.uk', contact_phone: '', vat_registered: true, archived: false,
  archived_at: null, created_at: '2026-10-06T09:00:00+00:00', updated_at: '2026-10-06T09:00:00+00:00',
  first_year_end: '2026-03-31', bank_accounts: [{ code: '1200', name: 'Bank current account', kind: 'current' }],
  rows: 0, to_review: 0, ...change,
})

const row = (change: Partial<SavedRow> = {}): SavedRow => ({
  id: 1, upload_id: 1, edited: false, original: null,
  date: '2026-10-01', description: 'October rent', direction: 'out', gross: '12000.00', vat: '2000.00',
  vat_treatment: null, vat_posted: '2000.00', net: '10000.00', account_code: '7100', contra_account_code: '2100',
  currency: 'GBP', source: 'pdf', method: 'llm', evidence: null, issues: [], document_type: 'invoice',
  counterparty: 'Business Cube', document_ref: 'rent', owed: '12000.00', paid_by: [], ...change,
})

test('search finds clients by company, responsible person or email, ignoring case', () => {
  const clients = [client(), client({ id: 2, name: 'Harbour & Lane LLP', contact_name: 'Matt Fisher',
                                      contact_email: 'matt@harbour.co.uk' })]
  assert.deepEqual(searchClients(clients, 'harbour').map(c => c.id), [2])
  assert.deepEqual(searchClients(clients, 'JENNY').map(c => c.id), [1])
  assert.deepEqual(searchClients(clients, '  ').map(c => c.id), [1, 2])
})

test('the client dialog needs a company name, a responsible person, a first year end and named bank accounts', () => {
  const fields = { name: ' ', business_type: 'limited_company' as const, contact_name: '', contact_email: 'jenny',
                   contact_phone: '', vat_registered: true, first_year_end: '',
                   bank_accounts: [{ code: '', name: ' ', kind: 'current' as const }] }
  assert.deepEqual(clientFormErrors(fields), {
    name: 'Enter the company name', contact_name: 'Enter the responsible person', contact_email: 'Enter a valid email',
    first_year_end: "Enter the client's first year end", bank_accounts: 'Name each bank account',
  })
  const fixed = { ...fields, name: 'Cube', contact_name: 'Jenny', contact_email: '', first_year_end: '2026-03-31',
                  bank_accounts: [{ code: '1200', name: 'Current', kind: 'current' as const }] }
  assert.deepEqual(clientFormErrors(fixed), {})
  // a phone number that isn't one, and a name another client has, are said before saving
  assert.deepEqual(clientFormErrors({ ...fixed, contact_phone: 'abc' }), { contact_phone: 'Enter a valid phone number' })
  assert.deepEqual(clientFormErrors({ ...fixed, contact_phone: '+44 (0)7700 900-123' }), {})
  assert.deepEqual(clientFormErrors(fixed, ['Other Ltd', ' cube ']), { name: 'Another client already has this name' })
  assert.deepEqual(clientFormErrors({ ...fixed, bank_accounts: [] }), { bank_accounts: 'Add at least one bank account' })
  assert.deepEqual(clientFormErrors({ ...fixed, bank_accounts: [...fixed.bank_accounts, { code: '', name: 'current', kind: 'savings' as const }] }),
                   { bank_accounts: 'Two bank accounts are called current: give each its own name' })
})

test('the dialog offers only as many bank accounts of a kind as the chart has codes for', () => {
  const current = (name: string) => ({ code: '', name, kind: 'current' as const })
  assert.equal(bankAccountsLeft([current('a'), current('b')], 'current'), 1)
  assert.equal(bankAccountsLeft([current('a'), current('b'), current('c')], 'current'), 0)
  assert.equal(bankAccountsLeft([], 'petty_cash'), 1)
  assert.equal(bankAccountsLeft([], 'credit_card'), 2)
})

test('the figures count the rows to review and what is still owed each way', () => {
  const sale = row({ id: 2, direction: 'in', account_code: '4000', document_ref: 'sale', gross: '500.00',
                     owed: '500.00', issues: [{ code: 'x', severity: 'warning', message: 'm' }] })
  assert.deepEqual(figuresOf([row(), sale]), { rows: 2, toReview: 1, toPay: '12000.00', toReceive: '500.00' })
})

test('the figures do not count a row left out of the books as one to review', () => {
  const warned = { issues: [{ code: 'x', severity: 'warning' as const, message: 'm' }] }
  const rows = [row(warned), row({ ...warned, id: 2, excluded: true }), row({ ...warned, id: 3, superseded_by: 'd1' })]
  assert.equal(figuresOf(rows).toReview, 1)
})

test('a picked file that repeats a saved upload is found by its fingerprint', () => {
  const uploads = [{ id: 7, name: 'BT-0905.pdf', sha256: 'abc' } as Upload]
  assert.equal(sameFileAs('abc', uploads)?.name, 'BT-0905.pdf')
  assert.equal(sameFileAs(null, uploads), undefined)
  assert.equal(sameFileAs('zzz', uploads), undefined)
})

test('a statement upload says whether its balances add up', () => {
  assert.equal(statementText({ status: 'ok', difference: null }), 'Balances add up')
  assert.equal(statementText({ status: 'gap', difference: '12.40' }), "Doesn't add up: £12.40")
  assert.equal(statementText({ status: 'none', difference: null }), 'No balances to check')
  assert.equal(statementText(null), null)
})

test('the edit form checks the amount, the VAT and the description', () => {
  const draft = draftOf(row())
  assert.deepEqual(rowEditErrors(draft), {})
  assert.deepEqual(rowEditErrors({ ...draft, gross: '0' }), { gross: 'Enter an amount above zero' })
  assert.deepEqual(rowEditErrors({ ...draft, vat: '12000' }), { vat: 'VAT must be below the amount' })
  assert.deepEqual(rowEditErrors({ ...draft, vat: '-1', description: ' ' }),
                   { vat: "VAT can't be negative", description: 'Enter a description' })
})

test("the edit form says what VAT is booked when the document prints none, so an empty VAT box doesn't read as none", () => {
  // Detroit City Burger, £13.55: the receipt prints the supplier's VAT number and no VAT amount; £2.26 is worked out.
  const burger = row({ description: 'Detroit City Burger', gross: '13.55', vat: null, vat_posted: '2.26', net: '11.29',
                       account_code: '7406', document_type: 'receipt' })
  assert.equal(vatWorkedOut(burger),
               '£2.26 VAT is booked, worked out from the total: the receipt prints no VAT amount. Leave this empty to keep it.')
  assert.equal(vatWorkedOut(row()), null)                                              // the invoice prints its VAT
  assert.equal(vatWorkedOut({ ...burger, vat_posted: '0.00', net: '13.55' }), null)   // none booked
  assert.equal(vatWorkedOut({ ...burger, vat_not_reclaimed: '2.26' }), null)          // held for its VAT invoice
})

test('an edit sends only what changed, with empty text as none', () => {
  const draft = { ...draftOf(row()), gross: '12000', account_code: '7103', vat: '', counterparty: ' Business Cube ' }
  assert.deepEqual(changesOf(row(), draft), { account_code: '7103', vat: null })
})

test('dates read as day and short month', () => {
  assert.equal(dayMonth('2026-10-06'), '6 Oct')
  assert.equal(dayMonth('2026-10-06T12:00:00+00:00'), '6 Oct')
  assert.equal(dayMonth(null), '')
})

test('the first-client invitation shows only when there are no clients at all', () => {
  // With every client archived, the invitation hid Show archived, so nothing could be restored.
  assert.equal(showsInvitation({ active: 0, archived: 0 }, false), true)
  assert.equal(showsInvitation({ active: 0, archived: 1 }, false), false)
  assert.equal(showsInvitation({ active: 2, archived: 0 }, false), false)
  assert.equal(showsInvitation({ active: 0, archived: 0 }, true), false)
})

test('an empty list says why it is empty', () => {
  assert.equal(emptyListText(false, ''), 'No active clients. Show archived to restore one.')
  assert.equal(emptyListText(false, 'zz'), 'No clients match your search.')
  assert.equal(emptyListText(true, ' '), 'No archived clients.')
  assert.equal(emptyListText(true, 'zz'), 'No clients match your search.')
})

test('retry skips a file that was saved after all, and queues the rest again', () => {
  // Final review #2: a file cancelled just after the server saved it was read and booked a second time on Retry.
  const file = new File(['x'], 'clearway.csv')
  const items: PickedFile[] = [
    { id: 1, file, hash: 'abc', status: 'cancelled', detail: 'Analysis cancelled.' },
    { id: 2, file, hash: 'def', status: 'failed', detail: "Groq's rate limit is used up" },
    { id: 3, file, hash: 'ghi', status: 'done', detail: '1 row saved' },
  ]
  const uploads = [{ id: 9, name: 'clearway.csv', sha256: 'abc', created_at: '2026-10-07T12:00:00+00:00' } as Upload]
  assert.deepEqual(requeue(items, uploads).map(item => [item.status, item.detail]), [
    ['skipped', 'Skipped: same file as clearway.csv, uploaded 7 Oct'], ['waiting', 'Waiting'], ['done', '1 row saved'],
  ])
})

test('counts say transactions, not rows', () => {
  // Asked for on 2026-10-07: a count of what was read or saved names transactions.
  assert.deepEqual([0, 1, 12].map(transactionCount), ['0 transactions', '1 transaction', '12 transactions'])
})

test('a line added to a document joins it: its reference, type and counterparty', () => {
  const claimLine = { document_type: 'expense_claim', document_ref: 'claim', counterparty: 'Jenny Hogg', direction: 'out',
                      date: '2026-09-30', account_code: '7400' } as unknown as Transaction
  const draft = { ...draftOf(lineTemplate(claimLine)), date: '2026-09-24', description: 'Jenny Hogg - Southgate Bath Car Park',
                  gross: '54.00', vat: '9.00' }
  assert.deepEqual(newRowFrom(draft, lineTemplate(claimLine)), {
    date: '2026-09-24', description: 'Jenny Hogg - Southgate Bath Car Park', counterparty: 'Jenny Hogg', direction: 'out',
    gross: '54.00', vat: '9.00', account_code: '7400', document_type: 'expense_claim', document_ref: 'claim',
  })
})

test('a transaction added on its own is a new document, and empty fields are left out', () => {
  const draft = { ...draftOf(lineTemplate(null)), description: 'Office chair', gross: '120.00', account_code: '0040' }
  assert.deepEqual(newRowFrom(draft, lineTemplate(null)), {
    date: null, description: 'Office chair', counterparty: null, direction: 'out', gross: '120.00', vat: null,
    account_code: '0040', document_type: 'receipt',
  })
})


test('the Edit list of accounts is in name order, with a saved account the business cannot choose first', () => {
  // Without their codes, accounts in code order (Office Equipment, Furniture, Cars, Vans, Bank Deposit…) were hard to scan.
  const account = (code: string, name: string) => ({ code, name, type: '', vat: '' })
  const chart = [account('7502', 'Telephone and Internet'), account('0040', 'Office Equipment'), account('7402', 'Hotels')]
  assert.deepEqual(accountList(chart, { code: '7402', name: 'Hotels' }, '7402').map(a => a.name),
                   ['Hotels', 'Office Equipment', 'Telephone and Internet'])
  assert.deepEqual(accountList(chart, { code: '3260', name: 'Drawings' }, '3260').map(a => a.name),
                   ['Drawings', 'Hotels', 'Office Equipment', 'Telephone and Internet'])
  assert.equal(accountList(chart, { code: '9999', name: null }, '9999')[0].name, 'Unknown account')   // not in the chart
  assert.deepEqual(accountList(chart, { code: '', name: null }, '').map(a => a.code), ['7402', '0040', '7502'])
})

const reading = (job_id: string, change: Partial<ReadingFile> = {}): ReadingFile =>
  ({ job_id, name: `${job_id}.jpg`, status: 'running', progress: 'Reading', year_start: '2026-04-01', ...change })

test('the page reloads once a file it saw being read has been saved', () => {
  assert.equal(someFinished([reading('a'), reading('b')], [reading('b')]), true)
  assert.equal(someFinished([reading('a')], [reading('a'), reading('c')]), false)
  assert.equal(someFinished([], []), false)
})

test('a file still being read says how far it got, or that it is waiting its turn', () => {
  assert.equal(readingLine(reading('a', { progress: 'Reading page 1 of 2' })), 'Reading page 1 of 2')
  assert.equal(readingLine(reading('a', { status: 'queued', progress: 'Queued' })), 'Waiting its turn')
})

test('leaving the page warns only while files are still to be sent', () => {
  const item = (status: PickedFile['status']) => ({ id: 1, file: {} as File, hash: null, status, detail: '' })
  assert.equal(unsent([item('waiting')]), true)
  assert.equal(unsent([item('sending')]), true)
  assert.equal(unsent([item('reading'), item('done'), item('skipped')]), false)
})

test('a receipt can be paid from any of the client\'s accounts, the owner or staff', () => {
  const accounts = [{ code: '1200', name: 'NatWest current', kind: 'current' }, { code: '1240', name: 'Amex', kind: 'credit_card' }]
  assert.deepEqual(paidFromOptions({ business_type: 'limited_company', bank_accounts: accounts } as never).map(a => a.code),
                   ['1200', '1240', '2250', '2110'])
  assert.deepEqual(paidFromOptions({ business_type: 'sole_trader', bank_accounts: accounts } as never).map(a => a.code),
                   ['1200', '1240', '3010', '2110'])
  assert.equal(paidFromOf({ bank_account: null } as never, { bank_accounts: accounts } as never), '1200')
  assert.equal(paidFromOf({ bank_account: '2250' } as never, { bank_accounts: accounts } as never), '2250')
})

test('owners are checked as the API checks them', () => {
  const o = (name: string, share = '') => ({ name, share })
  assert.equal(ownerError('sole_trader', []), '')
  assert.equal(ownerError('sole_trader', [o('Ann')]), 'A sole trader has no directors, partners or members to list')
  assert.equal(ownerError('limited_company', [o('Ann'), o(' ann ')]), 'Two directors are called ann: give each their own name')
  assert.equal(ownerError('llp', [o('')]), 'Name each member')
  assert.equal(ownerError('partnership', [o('Ann'), o('Raj')]), '')                       // shared equally
  assert.equal(ownerError('partnership', [o('Ann', '60'), o('Raj')]), "Give each partner's share of the profit, above 0%")
  assert.equal(ownerError('partnership', [o('Ann', '60'), o('Raj', '30')]), "The partners' shares of the profit add up to 90%: make them 100%")
  assert.equal(ownerError('partnership', [o('Ann', '62.5'), o('Raj', '37.5')]), '')
  assert.equal(ownerError('limited_company', 'ABCDE'.split('').map(n => o(n))), 'You can list up to 4 directors')
  assert.deepEqual(ownersToSend('partnership', [{ slot: 1, name: ' Ann ', share: ' 60 ' }, { name: 'Raj', share: '' }]),
                   [{ slot: 1, name: 'Ann', share: '60' }, { name: 'Raj', share: null }])
  assert.deepEqual(ownersToSend('sole_trader', [o('Ann')]), [])
})

test('each listed owner can have paid a receipt themselves', () => {
  const bank = [{ code: '1200', name: 'Barclays', kind: 'current' as const }]
  assert.deepEqual(paidFromOptions({ business_type: 'limited_company', bank_accounts: bank,
                                     owners: [{ slot: 0, name: 'Ann' }, { slot: 2, name: 'Raj' }] }).map(o => o.code),
                   ['1200', '2250', '2252', '2110'])
  assert.deepEqual(paidFromOptions({ business_type: 'partnership', bank_accounts: bank, owners: [{ slot: 1, name: 'Raj' }] })[1],
                   { code: '3011', name: "Raj's own money or card" })
  assert.deepEqual(paidFromOptions({ business_type: 'sole_trader', bank_accounts: bank }).map(o => o.code), ['1200', '3010', '2110'])
})

test('removing several files at once asks with how many files and transactions go', () => {
  const uploads = [{ id: 1, name: 'a.pdf', rows: 3 } as Upload, { id: 2, name: 'b.csv', rows: 1 } as Upload]
  assert.equal(removeUploadsText(uploads),
    "Remove 2 files and their 4 transactions? This can't be undone: analyse the files again to get them back.")
  assert.match(removeUploadsText([uploads[1]]), /^Remove 1 file and their 1 transaction\?/)
})
