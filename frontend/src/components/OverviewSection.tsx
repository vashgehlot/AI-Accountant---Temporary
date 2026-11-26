'use client'

import Link from 'next/link'
import { useEffect, useState, type ReactNode } from 'react'
import ClientDialog from '@/components/ClientDialog'
import { useClientYear } from '@/components/ClientYearContext'
import { useTodo } from '@/components/useTodo'
import { clientQuestions, questionsHref, waitingByYear, type Question } from '@/lib/chat'
import { postedTrialBalance } from '@/lib/api'
import { changeClient, getSummary, type ClientFields, type YearSummary } from '@/lib/clients'
import { BUSINESS_TYPES } from '@/lib/clientRules'
import { money, postedLedgerNote } from '@/lib/ledger'
import { bankCheckText, fullDate, linesFor } from '@/lib/sections'
import { newestFirst, listReviews, overviewReviewLine, unseenChanges } from '@/lib/reviews'
import { sectionHref } from '@/lib/years'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// A client's details, and how the year stands: whether it is open, what needs review or is unpaid, how the bank
// agrees with the statements, and whether the trial balance balances.
export default function OverviewSection() {
  const { client, year, years, ledger, reload } = useClientYear()
  const [summary, setSummary] = useState<YearSummary | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [asked, setAsked] = useState<Question[]>([])    // the client's questions, every year's, from every chat
  const [reviewLine, setReviewLine] = useState<string | null>(null)   // the AI review's last run; null when it has had none
  const [unposted, setUnposted] = useState<number | null>(null)   // changes not in the posted ledger; null until known

  // What the accountant chat has to say about the client; a failure just leaves these out.
  useEffect(() => {
    let current = true
    clientQuestions(client.id).then(qs => { if (current) setAsked(qs) }).catch(() => {})
    listReviews(client.id, year.start).then(runs => {
      if (!current) return
      const done = newestFirst(runs).filter(r => r.status === 'done')
      setReviewLine(overviewReviewLine(done[0]?.started_at ?? null, unseenChanges(runs)))
    }).catch(() => { if (current) setReviewLine(null) })
    postedTrialBalance(client.id, year.start)
      .then(tb => { if (current) setUnposted(tb.unposted_changes ?? 0) }).catch(() => { if (current) setUnposted(null) })
    return () => { current = false }
  }, [client.id, year.start, ledger])

  // The summary is worked out from the year's rows, so it is fetched again whenever they are loaded again.
  useEffect(() => {
    let current = true
    getSummary(client.id, year.start)
      .then(found => { if (current) { setSummary(found); setError('') } })
      .catch(e => { if (current) { setSummary(null); setError(message(e)) } })
    return () => { current = false }
  }, [client.id, year.start, ledger])

  const saveDetails = async (fields: ClientFields) => {
    await changeClient(client.id, fields)
    setEditing(false)
    await reload()
  }
  const link = (slug: 'transactions' | 'invoices' | 'bank' | 'trial-balance' | 'ai-review', text: string) => (
    <Link href={sectionHref(client.id, year.start, slug)} className="link-btn">{text}</Link>
  )
  const details: [string, string][] = [
    ['Business type', BUSINESS_TYPES[client.business_type]],
    ['Responsible person', client.contact_name || '—'],
    ['Email', client.contact_email || '—'],
    ['Phone', client.contact_phone || '—'],
    ['VAT', client.vat_registered ? 'Registered' : 'Not registered'],
    ['Company number', client.company_number || '—'],
    ['UTR', client.utr || '—'],
    ['VAT number', client.vat_number || '—'],
    ['PAYE reference', client.paye_reference || '—'],
    ['First year end', fullDate(client.first_year_end)],
    ['Bank accounts', client.bank_accounts.map(a => a.name).join(', ') || '—'],
  ]

  const ledgerNote = postedLedgerNote(unposted)
  const { need, error: todoError } = useTodo()

  const waiting = waitingByYear(asked, years, year.start)

  const summaryLine = [BUSINESS_TYPES[client.business_type], client.contact_name,
                       client.vat_number ? `VAT ${client.vat_number}` : ''].filter(Boolean).join(' · ')
  const tile = (label: string, value: ReactNode, to: ReactNode, warn = false) => (
    <div className={warn ? 'status-tile status-tile-warn' : 'status-tile'} key={label}>
      <div className="status-label">{label}</div>
      <div className="status-value">{value}</div>
      <div className="status-link">{to}</div>
    </div>
  )

  return (
    <>
      <section className="card section">
        <div className="section-head">
          <h2>{year.label}</h2>
          <span className={`badge ${year.closed ? 'badge-muted' : 'badge-accent'}`}>{year.closed ? 'Closed' : 'Open'}</span>
        </div>
        {year.closed && year.changed_since_closed && (
          <div className="notice notice-warn">
            <span>This closed year’s figures no longer match what was saved when it was closed.</span>
          </div>
        )}
        {error && <div className="notice notice-error">{error}</div>}
        <p className="todo-headline">
          {need === null && todoError ? <>Couldn’t count what is left to do: {todoError} {link('ai-review', 'AI review')}</>
            : need === null ? <span className="muted">Counting what is left to do…</span>
            : need === 0 ? <>Nothing to do. {link('ai-review', 'AI review')}</>
            : <Link href={sectionHref(client.id, year.start, 'ai-review')}><strong>{need} to do</strong> in the AI review</Link>}
        </p>
        {waiting.elsewhere.map(other => (
          <p key={other.start}><Link href={questionsHref(client.id, other.start)} className="link-btn">{other.count} {other.count === 1 ? 'question is' : 'questions are'} waiting in the {other.label.charAt(0).toLowerCase() + other.label.slice(1)}</Link></p>
        ))}
        {reviewLine && <p className="muted small"><Link href={sectionHref(client.id, year.start, 'ai-review')} className="link-btn">{reviewLine}</Link></p>}
        {summary?.missing_paperwork?.length ? (
          <div className="notice notice-warn">
            <strong>Missing paperwork</strong>
            <ul className="small">{summary.missing_paperwork.map(m => <li key={m}>{m}</li>)}</ul>
          </div>
        ) : null}
        {summary?.pointers?.map(p => <p key={p} className="muted small">{p}</p>)}
        {ledgerNote && <p className="muted small">{ledgerNote}</p>}
        {!summary && !error && <p className="muted">Loading the summary…</p>}
        {summary && (
          <div className="status-tiles">
            {summary.bank.map(check => tile(check.name, bankCheckText(check, linesFor(ledger, check.code).length),
                                            link("bank", "Bank"), check.difference !== null && Number(check.difference) !== 0))}
            {tile('Trial balance',
                  summary.trial_balance === 'balanced' ? 'Balances'
                    : <>Blocked{summary.problems.slice(0, 1).map(p => <div key={p} className="small status-clamp" title={p}>{p}</div>)}</>,
                  link('trial-balance', 'Trial balance'), summary.trial_balance !== 'balanced')}
            {tile('Unpaid sales', <span className="mono">{money(summary.unpaid_sales)}</span>, link('invoices', 'Invoices'))}
            {tile('Unpaid purchases', <span className="mono">{money(summary.unpaid_purchases)}</span>, link('invoices', 'Invoices'))}
          </div>
        )}
      </section>

      <details className="card section client-details">
        <summary>
          <h2>Client details</h2>
          <span className="muted small">{summaryLine}</span>
          {!client.archived && (
            <button type="button" className="btn btn-small" onClick={e => { e.preventDefault(); setEditing(true) }}>Edit details</button>
          )}
        </summary>
        <dl className="details">
          {details.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </details>
      {editing && <ClientDialog client={client} onCancel={() => setEditing(false)} onSave={saveDetails} />}
    </>
  )
}
