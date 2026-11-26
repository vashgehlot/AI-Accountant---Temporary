'use client'

import { useSearchParams } from 'next/navigation'
import { useMemo, useState } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import { useConfirm } from '@/components/ConfirmDialog'
import TransactionsTable from '@/components/TransactionsTable'
import { useRowDialogs } from '@/components/useRowDialogs'
import { changeRow, removeRow, type RowChange, type SavedRow } from '@/lib/clients'
import { CLOSED_YEAR_NOTICE } from '@/lib/clientRules'
import { linkedRows, money, removedForGood } from '@/lib/ledger'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// A client's year: its rows, editable. A closed year or an archived client shows them as they are.
export default function TransactionsSection() {
  const { client, year, ledger, show: showLedger } = useClientYear()
  const { ask, dialog: confirmDialog } = useConfirm()
  const [error, setError] = useState('')
  const { edit, add, dialogs } = useRowDialogs()
  // Rows being removed leave the table at once, and rows being changed are dimmed, while the API works.
  const [removing, setRemoving] = useState<Set<number>>(new Set())
  const [saving, setSaving] = useState<Set<number>>(new Set())
  const without = (set: Set<number>, id: number) => { const next = new Set(set); next.delete(id); return next }
  const listed = useMemo(() => (removing.size
    ? { ...ledger, transactions: ledger.transactions.filter(r => !removing.has(r.id)) } : ledger), [ledger, removing])
  const readOnly = year.closed || client.archived
  // ?row=7 (from the AI review's cards): open on that row, beside the rows its problems name; ?row=7&lines=1, on
  // every line of the document whose problem row 7 heads.
  const params = useSearchParams()
  const wanted = Number(params.get('row'))
  const show = linkedRows(ledger.transactions, wanted, params.get('lines') === '1')

  // A change the API answers with the year's ledger, which is shown as it comes back.
  const change = async (rowId: number, made: RowChange) => {
    setError('')
    setSaving(s => new Set(s).add(rowId))
    try { showLedger(await changeRow(client.id, rowId, made)) } catch (e) { setError(message(e)) }
    finally { setSaving(s => without(s, rowId)) }
  }
  // The row leaves the table as soon as the person confirms; it comes back, with why, if the API refuses.
  const remove = async (row: SavedRow) => {
    // A row typed in by hand is deleted; one read from a file is set aside, and its document still accounts for it.
    const question = removedForGood(row, ledger.uploads)
      ? `Remove "${row.description}" (${money(row.gross)})? This can't be undone. Its document's total is checked again without it.`
      : `Remove "${row.description}" (${money(row.gross)})? It is taken out of the books and stays listed, crossed out, so you can put it back.`
    if (!(await ask(question, 'Remove'))) return
    setError('')
    setRemoving(s => new Set(s).add(row.id))
    try { showLedger(await removeRow(client.id, row.id)) } catch (e) { setError(message(e)) }
    finally { setRemoving(s => without(s, row.id)) }
  }

  return (
    <>
      {year.closed && <div className="notice notice-warn">{CLOSED_YEAR_NOTICE}</div>}
      {error && <div className="notice notice-error">{error}</div>}
      <TransactionsTable key={wanted || 'all'} ledger={listed} readOnly={readOnly} show={show} saving={saving}
                         onChange={change} onEdit={edit} onAdd={add} onRemove={remove} />
      {dialogs}
      {confirmDialog}
    </>
  )
}
