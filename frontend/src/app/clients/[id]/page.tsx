'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import AddDocuments from '@/components/AddDocuments'
import ClientDialog from '@/components/ClientDialog'
import EditRowDialog from '@/components/EditRowDialog'
import { useConfirm } from '@/components/ConfirmDialog'
import TransactionsTable from '@/components/TransactionsTable'
import TrialBalancePanel from '@/components/TrialBalancePanel'
import UploadsList from '@/components/UploadsList'
import { ApiError } from '@/lib/api'
import {
  addManualRows, changeClient, changeRow, exportUrl, getLedger, removeRow, removeUpload, type ClientFields, type Ledger,
  type RowChange, type SavedRow, type Upload,
} from '@/lib/clients'
import { BUSINESS_TYPES, figuresOf, lineTemplate, newRowFrom, transactionCount, type EditDraft } from '@/lib/clientRules'
import type { Transaction } from '@/lib/api'
import { money } from '@/lib/ledger'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// One client: its details, its figures, its saved transactions and uploads, and its trial balance.
export default function ClientPage() {
  const params = useParams<{ id: string }>()
  const clientId = Number(params.id)
  const { ask, dialog: confirmDialog } = useConfirm()
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [missing, setMissing] = useState(false)
  const [error, setError] = useState('')
  const [editingClient, setEditingClient] = useState(false)
  const [editingRow, setEditingRow] = useState<SavedRow | null>(null)
  const [adding, setAdding] = useState<{ template: Transaction; title: string } | null>(null)   // a row being added
  const [version, setVersion] = useState(0)   // bumped whenever the rows change: a trial balance shown is cleared

  const show = useCallback((next: Ledger) => {
    setLedger(next)
    setVersion(v => v + 1)
    setError('')
  }, [])

  const load = useCallback(async () => {
    if (!Number.isInteger(clientId) || clientId < 1) {
      setMissing(true)
      return
    }
    try {
      show(await getLedger(clientId))
    } catch (e) {
      if (e instanceof ApiError && e.code === 'not_found') setMissing(true)
      else setError(message(e))
    }
  }, [clientId, show])

  useEffect(() => { load() }, [load])

  // A change the API answers with the whole ledger, worked out again.
  const act = useCallback(async (change: () => Promise<Ledger>) => {
    try { show(await change()) } catch (e) { setError(message(e)) }
  }, [show])

  if (missing) {
    return (
      <div className="empty card">
        <h1>Client not found</h1>
        <p className="muted">It may never have existed, or the link is wrong.</p>
        <Link href="/" className="btn">Back to clients</Link>
      </div>
    )
  }
  if (!ledger) return error ? <div className="notice notice-error">{error}</div> : <p className="muted">Loading…</p>

  const { client } = ledger
  const figures = figuresOf(ledger.transactions)
  const contact = [client.contact_name, client.contact_email, client.contact_phone].filter(Boolean).join(' · ')

  const archive = async () => {
    if (!(await ask(`Archive ${client.name}? You can restore it from Show archived.`, 'Archive'))) return
    try { await changeClient(client.id, { archived: true }); await load() } catch (e) { setError(message(e)) }
  }
  const restore = async () => {
    try { await changeClient(client.id, { archived: false }); await load() } catch (e) { setError(message(e)) }
  }
  const saveDetails = async (fields: ClientFields) => {
    await changeClient(client.id, fields)
    setEditingClient(false)
    await load()
  }
  const remove = async (upload: Upload) => {
    const question = `Remove ${upload.name} and its ${transactionCount(upload.rows)}? This can't be undone: analyse the file again to get them back.`
    if (await ask(question, 'Remove')) await act(() => removeUpload(client.id, upload.id))
  }
  const change = (rowId: number, rowChange: RowChange) => act(() => changeRow(client.id, rowId, rowChange))
  const removeOne = async (row: SavedRow) => {
    const question = `Remove "${row.description}" (${money(row.gross)})? This can't be undone. Its document's total is checked again without it.`
    if (await ask(question, 'Remove')) await act(() => removeRow(client.id, row.id))
  }
  const startAdding = (lineOf: SavedRow | null) => setAdding({
    template: lineTemplate(lineOf),
    title: lineOf ? `Add a line to ${lineOf.counterparty ?? 'this document'}` : 'Add a transaction',
  })
  const saveNew = async (draft: EditDraft) => {
    if (!adding) return
    show(await addManualRows(client.id, [newRowFrom(draft, adding.template)]))
    setAdding(null)
  }
  const saveRow = async (rowChange: RowChange) => {
    if (!editingRow) return
    show(await changeRow(client.id, editingRow.id, rowChange))
    setEditingRow(null)
  }

  return (
    <>
      <nav className="crumbs"><Link href="/">Clients</Link> / {client.name}</nav>
      <div className="page-head">
        <div>
          <h1>
            {client.name}{' '}
            <span className={client.vat_registered ? 'badge badge-accent' : 'badge badge-warn'}>
              {client.vat_registered ? 'VAT registered' : 'Not VAT registered'}
            </span>
          </h1>
          <p className="muted">{BUSINESS_TYPES[client.business_type]} · {contact}</p>
        </div>
        <div className="head-actions">
          {!client.archived && <button type="button" className="btn" onClick={() => setEditingClient(true)}>Edit details</button>}
          <a className="btn" href={exportUrl(client.id)} download>Export to Excel</a>
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
      <div className="figures">
        <div className="card figure"><div className="figure-label">Transactions</div><div className="figure-value">{figures.rows}</div></div>
        <div className="card figure">
          <div className="figure-label">To review</div>
          <div className={figures.toReview ? 'figure-value text-warn' : 'figure-value'}>{figures.toReview}</div>
        </div>
        <div className="card figure"><div className="figure-label">To pay</div><div className="figure-value">{money(figures.toPay)}</div></div>
        <div className="card figure"><div className="figure-label">To receive</div><div className="figure-value">{money(figures.toReceive)}</div></div>
      </div>
      {!client.archived && <AddDocuments clientId={client.id} uploads={ledger.uploads} onSaved={load} onLedger={show} />}
      <div className="workspace">
        <TransactionsTable ledger={ledger} readOnly={client.archived} onChange={change} onEdit={setEditingRow}
                           onAdd={startAdding} onRemove={removeOne} />
        <UploadsList uploads={ledger.uploads} readOnly={client.archived} onRemove={remove} />
      </div>
      <TrialBalancePanel clientId={client.id} version={version} hasRows={ledger.transactions.length > 0} />
      {/* The last step, in name only for now: it will add the books to the client's accounts, and does nothing yet. */}
      {!client.archived && (
        <div className="final-actions">
          <button type="button" className="btn btn-primary" title="Not connected yet">Add to account</button>
        </div>
      )}
      {editingClient && <ClientDialog client={client} onCancel={() => setEditingClient(false)} onSave={saveDetails} />}
      {editingRow && (
        <EditRowDialog row={editingRow} businessType={client.business_type}
                       onCancel={() => setEditingRow(null)} onSave={saveRow} />
      )}
      {adding && (
        <EditRowDialog row={adding.template} businessType={client.business_type} title={adding.title}
                       onCancel={() => setAdding(null)} onAdd={saveNew} />
      )}
      {confirmDialog}
    </>
  )
}
