'use client'

import { useEffect, useState, type FormEvent } from 'react'
import type { Transaction } from '@/lib/api'
import { addManualRows, listChart, type AccountChoice, type Client } from '@/lib/clients'
import { journalErrors, journalRow, type JournalDraft } from '@/lib/sections'

// A journal a person enters between two accounts of the chart: depreciation, an accrual or prepayment, a tax charge.
// It debits one account and credits the other for the amount, with no VAT, and no bank account is touched unless one
// is chosen.
export default function JournalDialog({ client, yearStart, yearEnd, onCancel, onSaved }: {
  client: Client
  yearStart: string
  yearEnd: string
  onCancel: () => void
  onSaved: () => Promise<void> | void
}) {
  const [draft, setDraft] = useState<JournalDraft>({ date: yearEnd, description: '', debit: '', credit: '', amount: '' })
  const [accounts, setAccounts] = useState<AccountChoice[]>([])
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const errors = journalErrors(draft)

  useEffect(() => {
    listChart().then(chart => setAccounts([...chart].sort((a, b) => a.code.localeCompare(b.code))))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const set = (field: keyof JournalDraft, value: string) => setDraft(d => ({ ...d, [field]: value }))
  const fieldError = (field: keyof JournalDraft) =>
    (showErrors && errors[field] ? <span className="field-error">{errors[field]}</span> : null)
  // A bank account or card is shown by the name the client gives it; the ones it doesn't have are left out.
  const own = new Map(client.bank_accounts.map(b => [b.code, b.name]))
  const options = accounts.filter(a => !/^12[0-4]/.test(a.code) || own.has(a.code))
    .map(a => ({ code: a.code, label: `${a.code} ${own.get(a.code) ?? a.name}` }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setShowErrors(true)
    if (Object.keys(errors).length) return
    setSaving(true)
    setError('')
    try {
      await addManualRows(client.id, [journalRow(draft) as Transaction], yearStart, 'Journal')
      await onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setSaving(false)
    }
  }

  const picker = (field: 'debit' | 'credit', label: string) => (
    <label className="field">
      <span>{label}</span>
      <select className="input" value={draft[field]} onChange={e => set(field, e.target.value)}>
        <option value="">Choose an account</option>
        {options.map(a => <option key={a.code} value={a.code}>{a.label}</option>)}
      </select>
      {fieldError(field)}
    </label>
  )

  return (
    <div className="overlay" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onCancel() }}
         onKeyDown={e => { if (e.key === 'Escape') onCancel() }}>
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="journal-title" onSubmit={submit} noValidate>
        <h2 id="journal-title">Add journal</h2>
        <p className="dialog-note">
          An entry between two accounts, such as depreciation, an accrual or a tax charge. No VAT is booked, and it
          is listed with the year&rsquo;s transactions, where it can be removed.
        </p>
        <div className="field-row">
          <label className="field">
            <span>Date</span>
            <input className="input" type="date" value={draft.date} onChange={e => set('date', e.target.value)} />
            {fieldError('date')}
          </label>
          <label className="field">
            <span>Amount (£)</span>
            <input className="input" inputMode="decimal" value={draft.amount} onChange={e => set('amount', e.target.value)} />
            {fieldError('amount')}
          </label>
        </div>
        <label className="field">
          <span>Description</span>
          <input className="input" value={draft.description} onChange={e => set('description', e.target.value)}
                 placeholder="Depreciation for the year" />
          {fieldError('description')}
        </label>
        <div className="field-row">
          {picker('debit', 'Debit')}
          {picker('credit', 'Credit')}
        </div>
        {error && <div className="notice notice-error">{error}</div>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Add journal'}</button>
        </div>
      </form>
    </div>
  )
}
