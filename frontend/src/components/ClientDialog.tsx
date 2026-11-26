'use client'

import { useState, type FormEvent } from 'react'
import type { AiReviewMode, BankAccountKind, BusinessType, Client, ClientFields, Owner } from '@/lib/clients'
import { bankAccountsLeft, BANK_KINDS, BUSINESS_TYPES, clientFormErrors, MAX_OWNERS, OWNER_WORDS, ownersToSend } from '@/lib/clientRules'

const NEW_CLIENT: ClientFields = {
  name: '', business_type: 'limited_company', contact_name: '', contact_email: '', contact_phone: '', vat_registered: true,
  first_year_end: '', bank_accounts: [{ code: '', name: 'Bank current account', kind: 'current' }], owners: [],
  ai_review: 'automatic',
}

// Adds a client, or edits one. The responsible person is the client's own contact. A bank account that has a code
// keeps it when saved (the server gives a new one the next free code of its kind).
export default function ClientDialog({ client, taken, onCancel, onSave }: {
  client?: Client
  taken?: string[]           // the other clients' names
  onCancel: () => void
  onSave: (fields: ClientFields) => Promise<void>
}) {
  const [fields, setFields] = useState<ClientFields>(() => (client ? {
    name: client.name, business_type: client.business_type, contact_name: client.contact_name,
    contact_email: client.contact_email, contact_phone: client.contact_phone, vat_registered: client.vat_registered,
    vat_from: client.vat_from ?? '',
    first_year_end: client.first_year_end, bank_accounts: client.bank_accounts.map(a => ({ ...a })),
    owners: (client.owners ?? []).map(o => ({ ...o, share: o.share ?? '' })),
    ai_review: client.ai_review ?? 'automatic', materiality: client.materiality ?? '', capitalise_from: client.capitalise_from ?? '', company_number: client.company_number ?? '', utr: client.utr ?? '',
    vat_number: client.vat_number ?? '', paye_reference: client.paye_reference ?? '',
    nature_of_business: client.nature_of_business ?? '', sic_code: client.sic_code ?? '',
  } : NEW_CLIENT))
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const errors = clientFormErrors(fields, taken)
  const set = <K extends keyof ClientFields>(key: K, value: ClientFields[K]) => setFields(f => ({ ...f, [key]: value }))
  const changeAccount = (index: number, change: { name?: string; kind?: BankAccountKind }) =>
    set('bank_accounts', fields.bank_accounts.map((a, i) => (i === index ? { ...a, ...change } : a)))
  const kindToAdd = (Object.keys(BANK_KINDS) as BankAccountKind[]).find(kind => bankAccountsLeft(fields.bank_accounts, kind) > 0)
  const owners = fields.owners ?? []
  const ownerWord = OWNER_WORDS[fields.business_type]
  const shared = fields.business_type === 'partnership' || fields.business_type === 'llp'
  const changeOwner = (index: number, change: Partial<Owner>) =>
    set('owners', owners.map((o, i) => (i === index ? { ...o, ...change } : o)))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setShowErrors(true)
    if (Object.keys(errors).length) return
    setSaving(true)
    setError('')
    try {
      await onSave({ ...fields, owners: ownersToSend(fields.business_type, fields.owners), materiality: fields.materiality || null, capitalise_from: fields.capitalise_from || null })
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
            {showErrors && errors.contact_phone && <span className="field-error">{errors.contact_phone}</span>}
          </label>
        </div>
        <label className="field">
          <span>First year end</span>
          <input className="input" type="date" value={fields.first_year_end}
                 onChange={e => set('first_year_end', e.target.value)} />
          <span className="hint">The end of the first year the books are kept for, e.g. 31 March 2026. Later years follow it.</span>
          {showErrors && errors.first_year_end && <span className="field-error">{errors.first_year_end}</span>}
        </label>
        <div className="field-row">
          <label className="field">
            <span>Nature of business</span>
            <input className="input" value={fields.nature_of_business ?? ''} maxLength={120}
                   onChange={e => set('nature_of_business', e.target.value)} placeholder="e.g. Web design agency" />
            <span className="hint">What the business does. A streaming subscription is a film or music business&apos;s cost, and anyone else&apos;s own.</span>
          </label>
          <label className="field">
            <span>SIC code</span>
            <input className="input" value={fields.sic_code ?? ''} onChange={e => set('sic_code', e.target.value)}
                   placeholder="e.g. 62012" inputMode="numeric" maxLength={5} />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span>Company number</span>
            <input className="input" value={fields.company_number ?? ''} onChange={e => set('company_number', e.target.value)}
                   placeholder="e.g. 09876543" />
          </label>
          <label className="field">
            <span>UTR</span>
            <input className="input" value={fields.utr ?? ''} onChange={e => set('utr', e.target.value)}
                   placeholder="e.g. 12345 67890" />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span>VAT number</span>
            <input className="input" value={fields.vat_number ?? ''} onChange={e => set('vat_number', e.target.value)}
                   placeholder="e.g. GB 123 4567 89" />
          </label>
          <label className="field">
            <span>PAYE reference</span>
            <input className="input" value={fields.paye_reference ?? ''} onChange={e => set('paye_reference', e.target.value)}
                   placeholder="e.g. 120/PA00123456" />
          </label>
        </div>
        <fieldset className="field bank-accounts">
          <legend>Bank accounts</legend>
          {fields.bank_accounts.map((account, i) => (
            <div className="bank-row" key={i}>
              <input className="input" value={account.name} aria-label={`Bank account ${i + 1} name`}
                     onChange={e => changeAccount(i, { name: e.target.value })} placeholder="e.g. Barclays current" />
              <select className="input" value={account.kind} aria-label={`Bank account ${i + 1} kind`}
                      disabled={!!account.code} title={account.code ? 'The kind of an account can’t change once it has a code.' : undefined}
                      onChange={e => changeAccount(i, { kind: e.target.value as BankAccountKind })}>
                {(Object.entries(BANK_KINDS) as [BankAccountKind, string][]).map(([kind, label]) => (
                  <option key={kind} value={kind} disabled={kind !== account.kind && bankAccountsLeft(fields.bank_accounts, kind) < 1}>
                    {label}
                  </option>
                ))}
              </select>
              <button type="button" className="link-btn danger" onClick={() => set('bank_accounts', fields.bank_accounts.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          ))}
          <div>
            <button type="button" className="btn btn-small" disabled={!kindToAdd}
                    onClick={() => kindToAdd && set('bank_accounts', [...fields.bank_accounts, { code: '', name: '', kind: kindToAdd }])}>
              Add bank account
            </button>
          </div>
          {showErrors && errors.bank_accounts && <span className="field-error">{errors.bank_accounts}</span>}
        </fieldset>
        {ownerWord && (
          <fieldset className="field bank-accounts">
            <legend>{ownerWord[0].toUpperCase() + ownerWord.slice(1)}s</legend>
            {owners.map((owner, i) => (
              <div className="bank-row" key={i}>
                <input className="input" value={owner.name} aria-label={`${ownerWord} ${i + 1} name`}
                       onChange={e => changeOwner(i, { name: e.target.value })} placeholder="e.g. Ann Lee" />
                {shared && (
                  <input className="input" inputMode="decimal" value={owner.share ?? ''} aria-label={`${ownerWord} ${i + 1} profit share`}
                         onChange={e => changeOwner(i, { share: e.target.value })} placeholder="Profit share %" />
                )}
                <button type="button" className="link-btn danger" onClick={() => set('owners', owners.filter((_, j) => j !== i))}>
                  Remove
                </button>
              </div>
            ))}
            <div>
              <button type="button" className="btn btn-small" disabled={owners.length >= MAX_OWNERS}
                      onClick={() => set('owners', [...owners, { name: '', share: '' }])}>
                Add {ownerWord}
              </button>
            </div>
            <span className="hint">
              Each {ownerWord} gets accounts of their own{fields.business_type === 'limited_company' ? ' (a director’s loan account)' : ''}.
              {shared ? ' Leave the shares empty to share the profit equally.' : ''}
            </span>
            {showErrors && errors.owners && <span className="field-error">{errors.owners}</span>}
          </fieldset>
        )}
        <label className="field">
          <span>AI review</span>
          <select className="input" value={fields.ai_review ?? 'automatic'} onChange={e => set('ai_review', e.target.value as AiReviewMode)}>
            <option value="automatic">Automatic</option>
            <option value="suggest">Suggest only</option>
            <option value="off">Off</option>
          </select>
          <span className="hint">After the books change and go quiet, the AI looks them over. Automatic makes the changes (you can undo them); Suggest only leaves them for you to apply.</span>
        </label>
        <label className="field">
          <span>Materiality (£, optional)</span>
          <input className="input" type="number" min="0" step="0.01" value={fields.materiality ?? ''}
                 onChange={e => set('materiality', e.target.value)} />
          <span className="hint">Leave empty to work it out from the client's figures (5% of profit, or 1% of costs). Items under 3% of it are left as coded and said so; facts that change the tax are always asked.</span>
        </label>
        <label className="field">
          <span>Capitalise equipment from (£ net, optional)</span>
          <input className="input" type="number" min="0" step="0.01" value={fields.capitalise_from ?? ''}
                 onChange={e => set('capitalise_from', e.target.value)} />
          <span className="hint">The client&apos;s policy: equipment and furniture costing less, net of the VAT reclaimed, is booked as a cost, with a note. Leave empty for no threshold.</span>
        </label>
        <label className="switch">
          <input type="checkbox" checked={fields.vat_registered} onChange={e => set('vat_registered', e.target.checked)} />
          <span>VAT registered</span>
        </label>
        {fields.vat_registered && (
          <label className="field">
            <span>VAT registered from</span>
            <input className="input" type="date" value={fields.vat_from ?? ''} onChange={e => set('vat_from', e.target.value)} />
            <span className="hint">Leave empty if the client was registered before the first year. Rows dated before this day book no VAT.</span>
          </label>
        )}
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
