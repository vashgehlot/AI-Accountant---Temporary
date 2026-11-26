'use client'

import { useState } from 'react'
import AddDocuments from '@/components/AddDocuments'
import { useClientYear } from '@/components/ClientYearContext'
import { useConfirm } from '@/components/ConfirmDialog'
import DocumentPanel from '@/components/DocumentPanel'
import UploadsList from '@/components/UploadsList'
import { removeUpload, setUploadBank, type Ledger, type Upload } from '@/lib/clients'
import { CLOSED_YEAR_NOTICE, removeUploadsText, transactionCount } from '@/lib/clientRules'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// A client's year: adding documents (upload, paste or by hand) and the files it holds, each of which can be looked at
// beside the list. A closed year or an archived client shows the files only.
export default function DocumentsSection() {
  const { client, year, ledger, reload, show, reading, checkReading } = useClientYear()
  const { ask, dialog: confirmDialog } = useConfirm()
  const [error, setError] = useState('')
  const readOnly = year.closed || client.archived

  const [removing, setRemoving] = useState<Set<number>>(new Set())   // files being removed: off the list at once
  const [viewing, setViewing] = useState<number | null>(null)          // the upload open beside the list
  const [selected, setSelected] = useState<Set<number>>(new Set())     // ticked for removing together
  // Gone from the list (removed, or being removed): the panel closes with it.
  const viewed = ledger.uploads.find(u => u.id === viewing && !removing.has(u.id)) ?? null
  // A change the API answers with the year's ledger, which is shown as it comes back.
  const act = async (change: () => Promise<Ledger>) => {
    setError('')
    try { show(await change()) } catch (e) { setError(message(e)) }
  }
  const remove = async (upload: Upload) => {
    const question = `Remove ${upload.name} and its ${transactionCount(upload.rows)}? This can't be undone: analyse the file again to get them back.`
    if (!(await ask(question, 'Remove'))) return
    setRemoving(s => new Set(s).add(upload.id))
    await act(() => removeUpload(client.id, upload.id))   // refused: the file is listed again, with why
    setRemoving(s => { const next = new Set(s); next.delete(upload.id); return next })
    setSelected(s => { const next = new Set(s); next.delete(upload.id); return next })
  }
  const select = (ids: number[], on: boolean) => setSelected(s => {
    const next = new Set(s)
    ids.forEach(id => (on ? next.add(id) : next.delete(id)))
    return next
  })
  // The ticked files, one after another; the first one refused stops the rest, which stay listed and ticked.
  const removeSelected = async () => {
    const chosen = ledger.uploads.filter(u => selected.has(u.id) && !removing.has(u.id))
    if (!chosen.length || !(await ask(removeUploadsText(chosen), `Remove ${chosen.length}`))) return
    const ids = chosen.map(u => u.id)
    setError('')
    setRemoving(s => new Set([...s, ...ids]))
    let last: Ledger | null = null
    const done: number[] = []
    try {
      for (const id of ids) {
        last = await removeUpload(client.id, id)
        done.push(id)
      }
    } catch (e) {
      setError(message(e))
    }
    if (last) show(last)
    setRemoving(s => { const next = new Set(s); ids.forEach(id => next.delete(id)); return next })
    setSelected(s => { const next = new Set(s); done.forEach(id => next.delete(id)); return next })
  }

  return (
    <>
      <h2>Documents</h2>
      {year.closed && <div className="notice notice-warn">{CLOSED_YEAR_NOTICE}</div>}
      {error && <div className="notice notice-error">{error}</div>}
      {!readOnly && (
        <AddDocuments clientId={client.id} yearStart={year.start} bankAccounts={client.bank_accounts}
                      company={client.business_type === 'limited_company'} uploads={ledger.uploads} reading={reading} onSaved={reload}
                      onSent={checkReading} />
      )}
      <div className={viewed ? 'todo-with-panel todo-panel-open' : 'todo-with-panel'}>
        <UploadsList uploads={ledger.uploads.filter(u => !removing.has(u.id))} bankAccounts={client.bank_accounts} readOnly={readOnly}
                     viewing={viewed?.id ?? null} selected={selected} onSelect={select} onRemoveSelected={removeSelected}
                     onView={upload => setViewing(v => (v === upload.id ? null : upload.id))}
                     onRemove={remove} onBank={(upload, code) => act(() => setUploadBank(client.id, upload.id, code))} />
        {viewed && (
          <DocumentPanel onClose={() => setViewing(null)} documents={[{
            upload: viewed, rowId: null, quotes: [], rows: ledger.transactions.filter(r => r.upload_id === viewed.id),
          }]} />
        )}
      </div>
      {confirmDialog}
    </>
  )
}
