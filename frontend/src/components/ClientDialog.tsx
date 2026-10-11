'use client'

import { useState, type FormEvent } from 'react'
import type { BusinessType, Client, ClientFields } from '@/lib/clients'
import { BUSINESS_TYPES, clientFormErrors } from '@/lib/clientRules'

const NEW_CLIENT: ClientFields = {
  name: '', business_type: 'limited_company', contact_name: '', contact_email: '', contact_phone: '', vat_registered: true,
}

// Adds a client, or edits one. The responsible person is the client's own contact.
export default function ClientDialog({ client, onCancel, onSave }: {
  client?: Client
  onCancel: () => void
  onSave: (fields: ClientFields) => Promise<void>
}) {
  const [fields, setFields] = useState<ClientFields>(() => (client ? {
    name: client.name, business_type: client.business_type, contact_name: client.contact_name,
    contact_email: client.contact_email, contact_phone: client.contact_phone, vat_registered: client.vat_registered,
  } : NEW_CLIENT))
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const errors = clientFormErrors(fields)
  const set = <K extends keyof ClientFields>(key: K, value: ClientFields[K]) => setFields(f => ({ ...f, [key]: value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setShowErrors(true)
    if (Object.keys(errors).length) return
    setSaving(true)
    setError('')
    try {
      await onSave(fields)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setSaving(false)
    }
  }

  return (
    <div className="overlay" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onCancel() }}
         onKeyDown={e => { if (e.key === 'Escape') onCancel() }}>
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="client-dialog-title" onSubmit={submit} noValidate>
        <h2 id="client-dialog-title">{client ? 'Edit client' : 'Add client'}</h2>
        <label className="field">
          <span>Company name</span>
          <input className="input" autoFocus value={fields.name} onChange={e => set('name', e.target.value)}
                 placeholder="e.g. Acme Corp Ltd" />
          {showErrors && errors.name && <span className="field-error">{errors.name}</span>}
        </label>
        <label className="field">
          <span>Business type</span>
          <select className="input" value={fields.business_type}
                  onChange={e => set('business_type', e.target.value as BusinessType)}>
            {Object.entries(BUSINESS_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Responsible person</span>
          <input className="input" value={fields.contact_name} onChange={e => set('contact_name', e.target.value)}
                 placeholder="e.g. Full Name" />
          {showErrors && errors.contact_name && <span className="field-error">{errors.contact_name}</span>}
        </label>
        <div className="field-row">
          <label className="field">
            <span>Email</span>
            <input className="input" type="email" value={fields.contact_email}
                   onChange={e => set('contact_email', e.target.value)} placeholder="e.g. name@company.co.uk" />
            {showErrors && errors.contact_email && <span className="field-error">{errors.contact_email}</span>}
          </label>
          <label className="field">
            <span>Phone</span>
            <input className="input" type="tel" value={fields.contact_phone}
                   onChange={e => set('contact_phone', e.target.value)} placeholder="e.g. +44 7700 900123" />
          </label>
        </div>
        <label className="switch">
          <input type="checkbox" checked={fields.vat_registered} onChange={e => set('vat_registered', e.target.checked)} />
          <span>VAT registered</span>
        </label>
        {error && <div className="notice notice-error">{error}</div>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Saving…' : client ? 'Save changes' : 'Add client'}
          </button>
        </div>
      </form>
    </div>
  )
}
