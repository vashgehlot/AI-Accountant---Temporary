// Run with: npm test (Node's own test runner; Node strips the TypeScript types itself).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import type { Transaction } from './api.ts'
import type { ClientSummary, SavedRow, Upload } from './clients.ts'
import type { PickedFile } from './clientRules.ts'
import {
  accountList, changesOf, clientFormErrors, dayMonth, draftOf, emptyListText, figuresOf, lineTemplate, newRowFrom, requeue,
  rowEditErrors, sameFileAs, searchClients, showsInvitation, statementText, transactionCount,
} from './clientRules.ts'

const client = (change: Partial<ClientSummary> = {}): ClientSummary => ({
  id: 1, name: 'Business Cube Ltd', business_type: 'limited_company', contact_name: 'Jenny Clarke',
  contact_email: 'jenny@businesscube.co.uk', contact_phone: '', vat_registered: true, archived: false,
  archived_at: null, created_at: '2026-10-06T09:00:00+00:00', updated_at: '2026-10-06T09:00:00+00:00',
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

test('the client dialog needs a company name, a responsible person and a real email', () => {
  const fields = { name: ' ', business_type: 'limited_company' as const, contact_name: '', contact_email: 'jenny',
                   contact_phone: '', vat_registered: true }
  assert.deepEqual(clientFormErrors(fields), {
    name: 'Enter the company name', contact_name: 'Enter the responsible person', contact_email: 'Enter a valid email',
  })
  assert.deepEqual(clientFormErrors({ ...fields, name: 'Cube', contact_name: 'Jenny', contact_email: '' }), {})
})

test('the figures count the rows to review and what is still owed each way', () => {
  const sale = row({ id: 2, direction: 'in', account_code: '4000', document_ref: 'sale', gross: '500.00',
                     owed: '500.00', issues: [{ code: 'x', severity: 'warning', message: 'm' }] })
  assert.deepEqual(figuresOf([row(), sale]), { rows: 2, toReview: 1, toPay: '12000.00', toReceive: '500.00' })
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
