'use client'

import { useEffect, useState, type FormEvent } from 'react'
import type { Transaction } from '@/lib/api'
import { listAccounts, type AccountChoice, type BusinessType, type RowChange, type SavedRow } from '@/lib/clients'
import { accountList, changesOf, DOCUMENT_TYPES, draftOf, rowEditErrors, type EditDraft, type EditErrors } from '@/lib/clientRules'

// Corrects what the model read on one row (counterparty and document type change for the whole document), or, with
// onAdd, adds a row: a new transaction, or a line of an existing document from a template (clientRules.lineTemplate).
export default function EditRowDialog({ row, businessType, onCancel, onSave, onAdd, title }: {
  row: SavedRow | Transaction
  businessType: BusinessType
  onCancel: () => void
  onSave?: (change: RowChange) => Promise<void>
  onAdd?: (draft: EditDraft) => Promise<void>
  title?: string
}) {
  const [draft, setDraft] = useState<EditDraft>(() => draftOf(row))
  const [accounts, setAccounts] = useState<AccountChoice[]>([])
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const errors: EditErrors = rowEditErrors(draft)

  useEffect(() => {
    listAccounts(businessType).then(setAccounts).catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [businessType])

  const set = (field: keyof EditDraft, value: string) => setDraft(d => ({ ...d, [field]: value }))
  const fieldError = (field: keyof EditErrors) =>
    (showErrors && errors[field] ? <span className="field-error">{errors[field]}</span> : null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setShowErrors(true)
    if (Object.keys(errors).length) return
    const change = changesOf(row, draft)
    if (!onAdd && !Object.keys(change).length) {
      onCancel()
      return
    }
    setSaving(true)
    setError('')
    try {
      if (onAdd) await onAdd(draft)
      else await onSave?.(change)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setSaving(false)
    }
  }

  const options = accountList(accounts, { code: row.account_code, name: row.account_name }, draft.account_code)

  return (
    <div className="overlay" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onCancel() }}
         onKeyDown={e => { if (e.key === 'Escape') onCancel() }}>
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="edit-row-title" onSubmit={submit} noValidate>
        <h2 id="edit-row-title">{title ?? 'Edit row'}</h2>
        <p className="dialog-note">
          {onAdd ? (row.document_ref ? 'The line joins this document: its total is checked again with it.'
                                     : 'A transaction you enter yourself, booked like any other.')
                 : 'Counterparty and document type change for every row of this document.'}
        </p>
        <div className="field-row">
          <label className="field">
            <span>Date</span>
            <input className="input" type="date" value={draft.date} onChange={e => set('date', e.target.value)} />
            {fieldError('date')}
          </label>
          <label className="field">
            <span>Document type</span>
            <select className="input" value={draft.document_type} onChange={e => set('document_type', e.target.value)}>
              {Object.entries(DOCUMENT_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
        <label className="field">
          <span>Description</span>
          <input className="input" value={draft.description} onChange={e => set('description', e.target.value)} />
          {fieldError('description')}
        </label>
        <label className="field">
          <span>Counterparty</span>
          <input className="input" value={draft.counterparty} onChange={e => set('counterparty', e.target.value)}
                 placeholder="Who was paid, or who paid" />
        </label>
        <div className="field-row">
          <label className="field">
            <span>Money</span>
            <select className="input" value={draft.direction} onChange={e => set('direction', e.target.value)}>
              <option value="out">Paid out</option>
              <option value="in">Received</option>
            </select>
          </label>
          <label className="field">
            <span>Amount (£)</span>
            <input className="input" inputMode="decimal" value={draft.gross} onChange={e => set('gross', e.target.value)} />
            {fieldError('gross')}
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span>VAT shown (£)</span>
            <input className="input" inputMode="decimal" value={draft.vat} onChange={e => set('vat', e.target.value)}
                   placeholder="None shown" />
            {fieldError('vat')}
          </label>
          <label className="field">
            <span>Account</span>
            <select className="input" value={draft.account_code} onChange={e => set('account_code', e.target.value)}>
              {!draft.account_code && <option value="">Choose an account</option>}
              {options.map(a => <option key={a.code} value={a.code}>{a.name}</option>)}
            </select>
            {fieldError('account_code')}
          </label>
        </div>
        {error && <div className="notice notice-error">{error}</div>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Saving…' : onAdd ? 'Add' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  )
}
