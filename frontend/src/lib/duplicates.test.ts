// Run with: npm test (Node's own test runner; Node strips the TypeScript types itself).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { possibleDuplicates, type PaymentRow } from './duplicates.ts'

const boiler: PaymentRow = { sourceId: 1, gross: '280.00', direction: 'out', date: '2025-05-08', kind: 'document',
                             ref: 'boiler', linked: [] }

test('a bill and the item of an agent statement that paid it are not duplicates', () => {
  // The agent paid the boiler bill out of the rent: the bill and that item were flagged as a possible duplicate.
  const item: PaymentRow = { ...boiler, sourceId: 2, date: '2025-05-09', ref: 'item', linked: ['boiler'] }
  assert.deepEqual(possibleDuplicates([{ ...boiler, linked: ['item'] }, item]), [null, null])
})

test('the same amount from two uploads a day apart is still flagged', () => {
  assert.deepEqual(possibleDuplicates([boiler, { ...boiler, sourceId: 2, date: '2025-05-09', ref: 'other' }]), [null, 0])
})

test('rows a person said are not the same are not flagged, whichever of the two holds the decision', () => {
  // Matt's checked duplicates kept their warning: there was no way to say they were two purchases.
  const other: PaymentRow = { ...boiler, id: 2, sourceId: 2, date: '2025-05-09', ref: 'other' }
  assert.deepEqual(possibleDuplicates([{ ...boiler, id: 1, apart: [2] }, other]), [null, null])
  assert.deepEqual(possibleDuplicates([{ ...boiler, id: 1 }, { ...other, apart: [1] }]), [null, null])
})

test('two receipts on the same expense claim are not duplicates: each pairs with its own line', () => {
  // Matt's M6 tolls of £12.00, northbound on 14 and southbound on 15 September, were flagged though the claim had both.
  const toll: PaymentRow = { sourceId: 1, gross: '12.00', direction: 'out', date: '2026-09-14', kind: 'document', ref: 'n',
                             claim: 'matt' }
  assert.deepEqual(possibleDuplicates([toll, { ...toll, sourceId: 2, date: '2026-09-15', ref: 's' }]), [null, null])
  assert.deepEqual(possibleDuplicates([toll, { ...toll, sourceId: 2, date: '2026-09-15', ref: 's', claim: null }]), [null, 0])
})
