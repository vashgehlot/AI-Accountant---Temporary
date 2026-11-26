// Run with: npm test (Node's own test runner; Node strips the TypeScript types itself).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import type { Year } from './clients.ts'
import { currentYear, isoDay, isSection, latestYear, sectionHref, SECTIONS, yearOption } from './years.ts'

const y = (start: string, change: Partial<Year> = {}): Year => ({
  start, end: `${Number(start.slice(0, 4)) + 1}-03-31`, label: `Year to 31 Mar ${Number(start.slice(0, 4)) + 1}`,
  closed: false, ...change,
})

test('section links carry the client and the year', () => {
  assert.equal(sectionHref(7, '2025-04-01', 'bank'), '/clients/7/2025-04-01/bank')
})

test('the year picker names the year end and says when it is closed', () => {
  assert.equal(yearOption({ start: '2025-04-01', end: '2026-03-31', label: 'Year to 31 Mar 2026', closed: true }),
               'Year to 31 Mar 2026 · closed')
  assert.equal(yearOption(y('2025-04-01')), 'Year to 31 Mar 2026')
})

test('the latest year is the one that ends last', () => {
  assert.equal(latestYear([y('2025-04-01'), y('2026-04-01')]).start, '2026-04-01')
  assert.equal(latestYear([y('2026-04-01'), y('2025-04-01')]).start, '2026-04-01')
})

test('the current year is the one that holds today, else the latest', () => {
  const years = [y('2024-04-01'), y('2025-04-01'), y('2026-04-01')]
  assert.equal(currentYear(years, '2025-10-30').start, '2025-04-01')
  assert.equal(currentYear(years, '2025-04-01').start, '2025-04-01')
  assert.equal(currentYear(years, '2026-03-31').start, '2025-04-01')
  assert.equal(currentYear(years, '2030-01-01').start, '2026-04-01')
  assert.equal(currentYear(years, '2020-01-01').start, '2026-04-01')
})

test("the current year is the one being worked on: today's when it holds rows, else the earliest open one that does", () => {
  // The website: the agency's books are all in the year to 31 Mar 2024, but the client list opened 2027's, empty.
  const years = [y('2023-04-01', { rows: 1354 }), y('2024-04-01'), y('2025-04-01', { rows: 0 }), y('2026-04-01', { rows: 0 })]
  assert.equal(currentYear(years, '2026-11-25').start, '2023-04-01')
  // A few documents dated after the year end are in the next year: the year to finish first is still the earlier one.
  assert.equal(currentYear([years[0], y('2024-04-01', { rows: 19 }), ...years.slice(2)], '2026-11-25').start, '2023-04-01')
  assert.equal(currentYear([...years.slice(0, 3), y('2026-04-01', { rows: 4 })], '2026-11-25').start, '2026-04-01')
  assert.equal(currentYear([y('2023-04-01', { rows: 9, closed: true }), y('2024-04-01')], '2024-11-25').start, '2024-04-01')
})

test('only the six sections are sections', () => {
  assert.deepEqual(SECTIONS.map(s => s.slug), ['overview', 'ai-review', 'documents', 'bank', 'invoices', 'transactions', 'trial-balance'])
  assert.equal(isSection('bank'), true)
  assert.equal(isSection('payroll'), false)
})

test('a day is written the way the API writes dates, in the computer\'s own calendar', () => {
  assert.equal(isoDay(new Date(2026, 2, 5, 23, 30)), '2026-03-05')
})
