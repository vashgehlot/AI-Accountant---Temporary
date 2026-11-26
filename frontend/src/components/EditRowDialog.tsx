'use client'

import { useEffect, useState, type FormEvent } from 'react'
import type { Transaction } from '@/lib/api'
import { listAccounts, type AccountChoice, type Client, type RowChange, type SavedRow } from '@/lib/clients'
import { accountList, changesOf, DOCUMENT_TYPES, draftOf, paidFromOf, paidFromOptions, rowEditErrors, VAT_TREATMENTS, vatWorkedOut, type EditDraft, type EditErrors } from '@/lib/clientRules'

// Corrects what the model read on one row (counterparty and document type change for the whole document), or, with
// onAdd, adds a row: a new transaction, or a line of an existing document from a template (clientRules.lineTemplate).
export default function EditRowDialog({ row, client, onCancel, onSave, onAdd, title }: {
  row: SavedRow | Transaction
  client: Client
  onCancel: () => void
  onSave?: (change: RowChange) => Promise<void>
  onAdd?: (draft: EditDraft) => Promise<void>
  title?: string
}) {
  const [draft, setDraft] = useState<EditDraft>(() => draftOf(row))
  const [accounts, setAccounts] = useState<AccountChoice[]>([])
  // What paid a saved receipt: the bank it is booked to, or whoever paid it themselves.
  const [paidFrom, setPaidFrom] = useState(() => paidFromOf(row, client))
  const [reverseCharge, setReverseCharge] = useState(() => !!row.reverse_charge)
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const errors: EditErrors = rowEditErrors(draft)
  const foreign = row.currency && row.currency !== 'GBP' ? row.currency : ''
  // VAT booked that the document doesn't print: said under the empty VAT box, which holds only VAT it prints.
  const workedOut = vatWorkedOut(row)

  useEffect(() => {
    listAccounts(client.id).then(setAccounts).catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [client.id])

  const set = (field: keyof EditDraft, value: string) => setDraft(d => ({ ...d, [field]: value }))
  const fieldError = (field: keyof EditErrors) =>
    (showErrors && errors[field] ? <span className="field-error">{errors[field]}</span> : null)

  // Only a receipt says what paid it: a bank line is on its statement's account, an invoice waits for its payment.
  const saysWhoPaid = !onAdd && draft.document_type === 'receipt' && row.document_type === 'receipt'

  // The reverse charge is said on the supplier's own invoice or receipt, for a client registered for VAT.
  const canReverse = !onAdd && client.vat_registered && draft.direction === 'out'
    && (draft.document_type === 'receipt' || draft.document_type === 'invoice')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setShowErrors(true)
    if (Object.keys(errors).length) return
    const change = changesOf(row, draft)
    // Saving a row read in another currency says its amount is now in pounds.
    if (foreign && !onAdd) change.currency = 'GBP'
    if (saysWhoPaid && paidFrom !== paidFromOf(row, client)) change.bank_account = paidFrom
    if (canReverse && reverseCharge !== !!row.reverse_charge) change.reverse_charge = reverseCharge
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

  // A bank account or card is shown by the name the client gives it.
  const named = accounts.map(a => ({ ...a, name: client.bank_accounts.find(b => b.code === a.code)?.name || a.name }))
  const options = accountList(named, { code: row.account_code, name: row.account_name }, draft.account_code)

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
        {foreign && !onAdd && (
          <div className="notice notice-warn">
            Read as {foreign} {row.gross}. Enter the amount{Number(row.vat) > 0 ? ' and VAT' : ''} in pounds, as the bank or card
            statement shows it. Saving books the row in pounds.
          </div>
        )}
        <div className="field-row">
          <label className="field">
            <span>Date</span>
            <input className="input" type="date" value={draft.date} onChange={e => set('date', e.target.value)} />
            {fieldError('date')}
          </label>
          <label className="field">
            <span>Document type</span>
            <select className="input" value={draft.document_type} onChange={e => set('document_type', e.target.value)}>
              {Object.entries(DOCUMENT_TYPES).filter(([value]) => value !== 'journal' || row.document_type === 'journal')
                .map(([value, label]) => <option key={value} value={value}>{label}</option>)}
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
            <span>{foreign && !onAdd ? 'Amount in pounds (£)' : 'Amount (£)'}</span>
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
            {!onAdd && draft.vat === '' && workedOut && <span className="hint">{workedOut}</span>}
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
        {client.vat_registered && (
          <label className="field">
            <span>VAT treatment</span>
            <select className="input" value={draft.vat_treatment} onChange={e => set('vat_treatment', e.target.value)}>
              {Object.entries(VAT_TREATMENTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        )}
        {saysWhoPaid && (
          <label className="field">
            <span>{draft.direction === 'in' ? 'Paid into' : 'Paid from'}</span>
            <select className="input" value={paidFrom} onChange={e => setPaidFrom(e.target.value)}>
              {paidFromOptions(client).map(a => <option key={a.code} value={a.code}>{a.name}</option>)}
            </select>
          </label>
        )}
        {canReverse && (
          <label className="switch">
            <input type="checkbox" checked={reverseCharge} onChange={e => setReverseCharge(e.target.checked)} />
            <span>Reverse charge: a service from abroad with no VAT charged</span>
          </label>
        )}
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
