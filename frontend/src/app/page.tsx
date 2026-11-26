'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import ClientDialog from '@/components/ClientDialog'
import { useConfirm } from '@/components/ConfirmDialog'
import { addClient, changeClient, getYears, listClients, type Client, type ClientFields, type ClientSummary, type Year } from '@/lib/clients'
import { BUSINESS_TYPES, dayMonth, emptyListText, searchClients, showsInvitation } from '@/lib/clientRules'
import { currentYear, isoDay, sectionHref } from '@/lib/years'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// The first page: every client, what needs a look, and the way in to each one.
export default function ClientsPage() {
  const router = useRouter()
  const { ask, dialog: confirmDialog } = useConfirm()
  const [showArchived, setShowArchived] = useState(false)
  const [clients, setClients] = useState<ClientSummary[] | null>(null)
  const [counts, setCounts] = useState({ active: 0, archived: 0 })
  const [query, setQuery] = useState('')
  const [years, setYears] = useState<Record<number, Year[]>>({})   // each client's years, once they have arrived
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<{ client?: Client } | null>(null)   // the dialog: adding, or editing one

  const load = useCallback(async () => {
    try {
      const [active, archived] = await Promise.all([listClients(false), listClients(true)])
      setCounts({ active: active.length, archived: archived.length })
      setClients(showArchived ? archived : active)
      setError('')
    } catch (e) {
      setError(message(e))
    }
  }, [showArchived])

  useEffect(() => { load() }, [load])

  // Each client's current year, found from its years. A client whose years can't be fetched shows a dash.
  useEffect(() => {
    let alive = true
    for (const c of clients ?? []) {
      getYears(c.id).then(list => { if (alive) setYears(known => ({ ...known, [c.id]: list })) }, () => undefined)
    }
    return () => { alive = false }
  }, [clients])

  const shown = useMemo(() => searchClients(clients ?? [], query), [clients, query])

  const save = async (fields: ClientFields) => {
    if (editing?.client) await changeClient(editing.client.id, fields)
    else await addClient(fields)
    setEditing(null)
    await load()
  }

  const archive = async (client: ClientSummary) => {
    if (!(await ask(`Archive ${client.name}? You can restore it from Show archived.`, 'Archive'))) return
    try { await changeClient(client.id, { archived: true }); await load() } catch (e) { setError(message(e)) }
  }

  const restore = async (client: ClientSummary) => {
    try { await changeClient(client.id, { archived: false }); await load() } catch (e) { setError(message(e)) }
  }

  const today = isoDay(new Date())
  // Straight to the current year's Overview once the years are known; until then the client's own address finds it.
  const hrefOf = (c: ClientSummary) =>
    years[c.id] ? sectionHref(c.id, currentYear(years[c.id], today).start, 'overview') : `/clients/${c.id}`
  const empty = clients !== null && showsInvitation(counts, showArchived)
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Clients</h1>
          <p className="muted">{counts.active} active · {counts.archived} archived</p>
        </div>
        {!showArchived && !empty && (
          <button type="button" className="btn btn-primary" onClick={() => setEditing({})}>Add client</button>
        )}
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      {empty ? (
        <div className="empty card">
          <h2>Add your first client</h2>
          <p className="muted">Each client keeps its documents, its transactions and its trial balance.</p>
          <button type="button" className="btn btn-primary" onClick={() => setEditing({})}>Add client</button>
        </div>
      ) : (
        <>
          <div className="toolbar">
            <input className="input search" type="search" value={query} onChange={e => setQuery(e.target.value)}
                   placeholder="Search clients or contacts" aria-label="Search clients or contacts" />
            <button type="button" className="btn btn-ghost" onClick={() => setShowArchived(s => !s)}>
              {showArchived ? 'Show active' : 'Show archived'}
            </button>
          </div>
          <div className="card table-card">
            <table className="table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Responsible person</th>
                  <th>VAT</th>
                  <th>Current year</th>
                  <th className="num">Transactions</th>
                  <th className="num">To review</th>
                  <th className="num">Updated</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {clients === null && <tr><td colSpan={8} className="muted">Loading clients…</td></tr>}
                {shown.map(c => (
                  <tr key={c.id} className="clickable" onClick={() => router.push(hrefOf(c))}>
                    <td>
                      <Link href={hrefOf(c)} className="strong" onClick={e => e.stopPropagation()}>{c.name}</Link>
                      <div className="muted small">{BUSINESS_TYPES[c.business_type]}</div>
                      {!!c.ai_unseen && <span className="badge badge-accent">AI: {c.ai_unseen} new {c.ai_unseen === 1 ? 'change' : 'changes'}</span>}
                    </td>
                    <td>
                      {c.contact_name}
                      <div className="muted small">{[c.contact_email, c.contact_phone].filter(Boolean).join(' · ')}</div>
                    </td>
                    <td>
                      <span className={c.vat_registered ? 'badge badge-accent' : 'badge badge-warn'}>
                        {c.vat_registered ? 'Registered' : 'Not registered'}
                      </span>
                    </td>
                    <td>
                      {years[c.id] ? (() => {
                        const year = currentYear(years[c.id], today)
                        return (
                          <>
                            {year.label}{' '}
                            <span className={year.closed ? 'badge badge-muted' : 'badge badge-accent'}>
                              {year.closed ? 'Closed' : 'Open'}
                            </span>
                          </>
                        )
                      })() : <span className="muted">–</span>}
                    </td>
                    <td className="num">{c.rows}</td>
                    <td className={c.to_review ? 'num text-warn' : 'num'}>{c.to_review}</td>
                    <td className="num muted">{dayMonth(c.updated_at)}</td>
                    <td className="row-actions" onClick={e => e.stopPropagation()}>
                      {showArchived ? (
                        <button type="button" className="link-btn" onClick={() => restore(c)}>Restore</button>
                      ) : (
                        <>
                          <button type="button" className="link-btn" onClick={() => setEditing({ client: c })}>Edit</button>
                          <button type="button" className="link-btn" onClick={() => archive(c)}>Archive</button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
                {clients !== null && !shown.length && (
                  <tr>
                    <td colSpan={8} className="muted">
                      {emptyListText(showArchived, query)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
      {editing && <ClientDialog client={editing.client}
                                taken={(clients ?? []).filter(c => c.id !== editing.client?.id).map(c => c.name)} onCancel={() => setEditing(null)} onSave={save} />}
      {confirmDialog}
    </>
  )
}
