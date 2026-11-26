'use client'

import Link from 'next/link'
import { useParams, useRouter, useSelectedLayoutSegment } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ClientYearContext, type ClientYear } from '@/components/ClientYearContext'
import { useConfirm } from '@/components/ConfirmDialog'
import { ApiError } from '@/lib/api'
import { changeClient, getReading, getYearLedger, getYears, yearExportUrl, type Ledger } from '@/lib/clients'
import { BUSINESS_TYPES, someFinished, type ReadingFile } from '@/lib/clientRules'
import { isSection, SECTIONS, sectionHref, yearOption } from '@/lib/years'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const READING_POLL_MS = 3_000

// A client's year: its name and year picker on top, the side menu of sections on the left and the section in the
// middle. Loads the year once for all its sections.
export default function ClientYearLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string; year: string }>()
  const router = useRouter()
  const segment = useSelectedLayoutSegment()
  const { ask, dialog: confirmDialog } = useConfirm()
  const clientId = Number(params.id)
  const start = params.year
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [missing, setMissing] = useState<'client' | 'year' | null>(null)
  const [error, setError] = useState('')
  const latest = useRef(0)   // the newest load: an answer for a client or year left behind is dropped

  const reload = useCallback(async () => {
    const ticket = ++latest.current
    if (!Number.isInteger(clientId) || clientId < 1) { setMissing('client'); return }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) { setMissing('year'); return }
    try {
      const next = await getYearLedger(clientId, start)
      if (ticket !== latest.current) return
      setLedger(next)
      setMissing(null)
      setError('')
    } catch (e) {
      if (ticket !== latest.current) return
      if (e instanceof ApiError && e.code === 'not_found') {
        // Either the year or the client is unknown: the client's years say which.
        const clientKnown = await getYears(clientId).then(() => true, () => false)
        if (ticket === latest.current) setMissing(clientKnown ? 'year' : 'client')
      } else {
        setError(message(e))
      }
    }
  }, [clientId, start])

  useEffect(() => {
    setLedger(null)
    setMissing(null)
    setError('')
    reload()
  }, [reload])

  // A change is answered with its year's ledger: shown as it is, so the page doesn't wait for a second fetch. A
  // change that moved the row into another year is answered with that year's, so this one is fetched again.
  const show = useCallback((next: Ledger) => {
    if (next.year.start !== start) { reload(); return }
    latest.current++   // a load still on its way is older than this
    setLedger(next)
    setError('')
  }, [start, reload])

  // The files the API is reading for the client, whichever page sent them and across a refresh: looked at when the
  // year opens and every few seconds while any is being read; the year is fetched again as each one is saved.
  const [reading, setReading] = useState<ReadingFile[]>([])
  const [readingTick, setReadingTick] = useState(0)
  const checkReading = useCallback(() => setReadingTick(n => n + 1), [])
  const seen = useRef<ReadingFile[]>([])
  useEffect(() => {
    if (!Number.isInteger(clientId) || clientId < 1) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const look = async () => {
      try {
        const now = await getReading(clientId)
        if (stopped) return
        if (someFinished(seen.current, now)) reload()
        seen.current = now
        setReading(now)
        if (now.length) timer = setTimeout(look, READING_POLL_MS)
      } catch {
        if (!stopped) timer = setTimeout(look, READING_POLL_MS * 3)   // the API may be restarting
      }
    }
    look()
    return () => { stopped = true; clearTimeout(timer) }
  }, [clientId, reload, readingTick])

  const value = useMemo<ClientYear | null>(() => ledger && {
    client: ledger.client, year: ledger.year, years: ledger.years, ledger, reload, show, error, reading, checkReading,
  }, [ledger, reload, show, error, reading, checkReading])

  if (missing === 'client') {
    return (
      <div className="empty card">
        <h1>Client not found</h1>
        <p className="muted">It may never have existed, or the link is wrong.</p>
        <Link href="/" className="btn">Back to clients</Link>
      </div>
    )
  }
  if (missing === 'year') {
    return (
      <div className="empty card">
        <h1>Year not found</h1>
        <p className="muted">This client has no year starting on that date.</p>
        <Link href={`/clients/${clientId}`} className="btn">Go to the latest year</Link>
      </div>
    )
  }
  if (!value) return error ? <div className="notice notice-error">{error}</div> : <p className="muted">Loading…</p>

  const { client, year, years } = value
  const contact = [client.contact_name, client.contact_email, client.contact_phone].filter(Boolean).join(' · ')
  const open = segment && isSection(segment) ? segment : 'overview'

  const archive = async () => {
    if (!(await ask(`Archive ${client.name}? You can restore it from Show archived.`, 'Archive'))) return
    try { await changeClient(client.id, { archived: true }); await reload() } catch (e) { setError(message(e)) }
  }
  const restore = async () => {
    try { await changeClient(client.id, { archived: false }); await reload() } catch (e) { setError(message(e)) }
  }

  return (
    <ClientYearContext.Provider value={value}>
      <nav className="crumbs"><Link href="/">Clients</Link> / {client.name}</nav>
      <div className="page-head">
        <div>
          <h1>
            {client.name}{' '}
            <span className={client.vat_registered ? 'badge badge-accent' : 'badge badge-warn'}>
              {client.vat_registered ? 'VAT registered' : 'Not VAT registered'}
            </span>
          </h1>
          <p className="muted">{BUSINESS_TYPES[client.business_type]}{contact && ` · ${contact}`}</p>
        </div>
        <div className="head-actions">
          <label className="year-picker">
            <span>Year</span>
            <select className="input" value={year.start} aria-label="Year"
                    onChange={e => router.push(sectionHref(client.id, e.target.value, open))}>
              {years.map(y => <option key={y.start} value={y.start}>{yearOption(y)}</option>)}
            </select>
          </label>
          <a className="btn" href={yearExportUrl(client.id, year.start)} download>Export to Excel</a>
          {!client.archived && <button type="button" className="btn btn-ghost" onClick={archive}>Archive</button>}
        </div>
      </div>
      {client.archived && (
        <div className="notice notice-warn">
          <span>Archived. Restore to add documents or make changes.</span>
          <button type="button" className="btn" onClick={restore}>Restore</button>
        </div>
      )}
      {error && <div className="notice notice-error">{error}</div>}
      <div className="client-space">
        <nav className="side-menu" aria-label="Sections">
          {SECTIONS.map(s => (
            <Link key={s.slug} href={sectionHref(client.id, year.start, s.slug)}
                  aria-current={segment === s.slug ? 'page' : undefined}>
              {s.title}
            </Link>
          ))}
        </nav>
        <div className="client-section">{children}</div>
      </div>
      {confirmDialog}
    </ClientYearContext.Provider>
  )
}
