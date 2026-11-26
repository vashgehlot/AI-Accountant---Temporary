'use client'

import type { BankAccount, Upload } from '@/lib/clients'
import { dayMonth, statementText, transactionCount } from '@/lib/clientRules'
import { viewable } from '@/lib/suggestions'

// What was added to the year, newest first, with each bank statement's account (changeable when the client has
// several) and balance check, View (the file beside the list, in a closed year too) and Remove. Ticked files can be
// removed together.
export default function UploadsList({ uploads, bankAccounts, readOnly, viewing, selected, onView, onRemove, onBank, onSelect,
                                      onRemoveSelected }: {
  uploads: Upload[]
  bankAccounts: BankAccount[]
  readOnly: boolean
  viewing: number | null             // the upload open beside the list
  onView: (upload: Upload) => void
  onRemove: (upload: Upload) => void
  onBank: (upload: Upload, code: string) => void
  selected: Set<number>              // the uploads ticked for removing together
  onSelect: (ids: number[], on: boolean) => void
  onRemoveSelected: () => void
}) {
  const ticked = uploads.filter(u => selected.has(u.id)).length
  const all = uploads.length > 0 && ticked === uploads.length
  return (
    <section className="card section">
      <div className="section-head">
        <h2>Uploads</h2>
        <span className="muted small">{uploads.length}</span>
        {!readOnly && uploads.length > 1 && (
          <label className="small upload-select-all">
            <input type="checkbox" checked={all} aria-label="Select all uploads" ref={el => { if (el) el.indeterminate = ticked > 0 && !all }}
                   onChange={e => onSelect(uploads.map(u => u.id), e.target.checked)} />
            Select all
          </label>
        )}
        {!readOnly && ticked > 0 && (
          <button type="button" className="btn btn-small btn-danger upload-remove-selected" onClick={onRemoveSelected}>Remove {ticked}</button>
        )}
      </div>
      {!uploads.length ? <p className="muted small">Nothing added yet.</p> : (
        <ul className="upload-list">
          {uploads.map(upload => {
            const check = statementText(upload.statement)
            const status = upload.statement?.status
            const isStatement = !!upload.statement || upload.bank_account != null
            const account = upload.bank_account ?? bankAccounts[0]?.code ?? ''
            return (
              <li key={upload.id} className={viewing === upload.id ? 'upload-viewing' : undefined}>
                <div className="upload-title">
                  {!readOnly && (
                    <input type="checkbox" checked={selected.has(upload.id)} aria-label={`Select ${upload.name}`}
                           onChange={e => onSelect([upload.id], e.target.checked)} />
                  )}
                  <div className="upload-name" title={upload.name}>{upload.name}</div>
                </div>
                <div className="muted small">{transactionCount(upload.rows)} · {dayMonth(upload.created_at)}</div>
                {isStatement && bankAccounts.length > 1 && (readOnly ? (
                  <div className="muted small">On {bankAccounts.find(a => a.code === account)?.name ?? account}</div>
                ) : (
                  <label className="small upload-bank">
                    <span className="muted">On</span>
                    <select className="input" value={account} aria-label={`Bank account for ${upload.name}`}
                            onChange={e => onBank(upload, e.target.value)}>
                      {bankAccounts.map(a => <option key={a.code} value={a.code}>{a.name}</option>)}
                    </select>
                  </label>
                ))}
                {check && (
                  <div className={`small ${status === 'gap' ? 'text-warn' : status === 'ok' ? 'text-ok' : 'muted'}`}>{check}</div>
                )}
                {upload.warnings.length > 0 && (
                  <details className="small">
                    <summary>{upload.warnings.length} warning{upload.warnings.length === 1 ? '' : 's'}</summary>
                    {upload.warnings.map((warning, i) => <div key={i} className="muted">{warning}</div>)}
                  </details>
                )}
                <div className="upload-actions">
                  {viewable(upload) && (
                    <button type="button" className="link-btn" aria-pressed={viewing === upload.id} onClick={() => onView(upload)}>
                      View
                    </button>
                  )}
                  {!readOnly && (
                    <button type="button" className="link-btn danger" onClick={() => onRemove(upload)}>Remove</button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
