// Run with: npm test. A stubbed fetch stands in for the API.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { analysisForm, analyze } from './api.ts'

const reply = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

test('a cancel that arrives after the job saved its rows still returns them', async () => {
  // Final review #2: the page said "cancelled" for a job that had already saved, and Retry booked it twice.
  const calls: string[] = []
  let cancelled = false
  const result = { transactions: [], warnings: [], model: 'fake-model', upload_id: 7 }
  const job = (status: string) => ({ job_id: 'j1', status, progress: 'Saving', result: status === 'succeeded' ? result : null, error: null })
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    if (init?.method === 'POST') return reply({ job_id: 'j1', status: 'queued' })
    if (init?.method === 'DELETE') return reply(job('running'))
    if (calls.filter(c => c === 'GET /api/jobs/j1').length === 1) {
      cancelled = true            // the person clicks Cancel while the job is saving
      return reply(job('running'))
    }
    return reply(job('succeeded'))
  }) as typeof fetch
  assert.deepEqual(await analyze(new FormData(), () => {}, () => cancelled), result)
  assert.equal(calls.filter(c => c.startsWith('DELETE')).length, 1)
})

test('an analysis tells the API it comes from these pages', async () => {
  // Final review #4: the API refuses an analysis without X-LedgerSync, which a form on another site can't send.
  let sent: Headers | undefined
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      sent = new Headers(init.headers)
      return reply({ job_id: 'j1', status: 'queued' })
    }
    return reply({ job_id: 'j1', status: 'succeeded', progress: '', result: { transactions: [], warnings: [], model: 'm' }, error: null })
  }) as typeof fetch
  await analyze(new FormData(), () => {}, () => false)
  assert.equal(sent?.get('X-LedgerSync'), '1')
})

test('an upload names its client, year and bank account', () => {
  const file = new File(['a,b'], 'bank.csv')
  const data = analysisForm({ file }, { clientId: 4, yearStart: '2025-04-01', bankAccount: '1201' })
  assert.equal(data.get('client_id'), '4')
  assert.equal(data.get('year_start'), '2025-04-01')
  assert.equal(data.get('bank_account'), '1201')
  assert.equal((data.get('file') as File).name, 'bank.csv')
  const loose = analysisForm({ text: 'Rent - paid GBP 100' })
  assert.equal(loose.get('text'), 'Rent - paid GBP 100')
  assert.equal(loose.has('client_id'), false)
  assert.equal(analysisForm({ text: 'x' }, { clientId: 4, yearStart: '2025-04-01', bankAccount: '' }).has('bank_account'), false)
})
