'use client'

import { useEffect, useRef, useState } from 'react'
import { getOpening, listChart, putOpening, type AccountChoice, type Client, type OpenItem, type OpeningBalances } from '@/lib/clients'
import { openingAccounts, openingErrors } from '@/lib/sections'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// What a person types is text until it is saved: a blank amount is nothing.
interface LineDraft { code: string; debit: string; credit: string }
interface ItemDraft { id: string; direction: 'in' | 'out'; counterparty: string; number: string; date: string; amount: string }

const blank = (amount: string) => (Number(amount) === 0 ? '' : amount)
const AMOUNT = /^(\d+(\.\d{0,2})?|\.\d{1,2})?$/

// The first year's opening balances: the amounts on balance sheet accounts, and the unpaid invoices that make up
// Debtors and Creditors, so a payment in any year can clear them. Read-only once the year is closed.
export default function OpeningBalancesForm({ client, readOnly, onSaved }: {
  client: Client
  readOnly: boolean
  onSaved: () => Promise<void>
}) {
  const [lines, setLines] = useState<LineDraft[]>([])
  const [items, setItems] = useState<ItemDraft[]>([])
  const [accounts, setAccounts] = useState<AccountChoice[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const made = useRef(0)

  const show = (o: OpeningBalances) => {
    setLines(o.lines.map(l => ({ code: l.code, debit: blank(l.debit), credit: blank(l.credit) })))
    setItems(o.unpaid.map(i => ({
      id: i.id, direction: i.direction, counterparty: i.counterparty, number: i.number ?? '', date: i.date ?? '', amount: i.amount,
    })))
  }

  useEffect(() => {
    let current = true
    Promise.all([getOpening(client.id), listChart()])
      .then(([opening, chart]) => {
        if (!current) return
        show(opening)
        setAccounts(openingAccounts(chart, client))
        setLoaded(true)
      })
      .catch(e => { if (current) setError(message(e)) })
    return () => { current = false }
    // The client's bank accounts matter only for the choice of accounts, which is made once.
  }, [client.id])

  const money = (text: string) => (text.trim() === '' ? '0.00' : Number(text).toFixed(2))
  const draft = (): OpeningBalances => ({
    lines: lines.map(l => ({ code: l.code, debit: money(l.debit), credit: money(l.credit) })),
    unpaid: items.map(i => ({
      id: i.id, direction: i.direction, counterparty: i.counterparty.trim(), amount: money(i.amount),
      number: i.number.trim() || null, date: i.date || null,
    } satisfies OpenItem)),
  })
  const badAmount = [...lines.flatMap(l => [l.debit, l.credit]), ...items.map(i => i.amount)].some(a => !AMOUNT.test(a.trim()))
  const problems = badAmount ? ['Enter each amount in pounds and pence, like 1200.50.'] : openingErrors(draft())
  const touched = lines.length > 0 || items.length > 0

  const changed = () => { setSaved(false); setError('') }
  const setLine = (i: number, change: Partial<LineDraft>) => { changed(); setLines(ls => ls.map((l, j) => (j === i ? { ...l, ...change } : l))) }
  const setItem = (i: number, change: Partial<ItemDraft>) => { changed(); setItems(is => is.map((x, j) => (j === i ? { ...x, ...change } : x))) }
  const addLine = () => {
    const free = accounts.find(a => !lines.some(l => l.code === a.code)) ?? accounts[0]
    if (!free) return
    changed()
    setLines(ls => [...ls, { code: free.code, debit: '', credit: '' }])
  }
  const addItem = (direction: 'in' | 'out') => {
    changed()
    setItems(is => [...is, { id: `open-${Date.now().toString(36)}-${made.current++}`, direction, counterparty: '', number: '', date: '', amount: '' }])
  }

  const save = async () => {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      show(await putOpening(client.id, draft()))
      setSaved(true)
      await onSaved()
    } catch (e) {
      setError(message(e))
    } finally {
      setSaving(false)
    }
  }

  // An account the chart no longer offers is still shown, so a saved line is never silently changed.
  const optionsFor = (code: string) => (accounts.some(a => a.code === code) ? accounts : [...accounts, { code, name: '', type: '', vat: '' }])

  if (!loaded) return error ? <div className="notice notice-error">{error}</div> : <p className="muted">Loading opening balances…</p>

  return (
    <section className="card section opening">
      <div className="section-head">
        <h2>Opening balances</h2>
      </div>
      <p className="muted small">
        {readOnly
          ? 'What the first year started with, from the client’s last accounts. Reopen the year to change them.'
          : 'What the first year starts with, from the client’s last accounts. Debits and credits must be the same.'}
      </p>

      <h3>Accounts</h3>
      {!lines.length && <p className="muted">No opening balances yet.</p>}
      <div className="opening-rows">
        {lines.map((l, i) => (
          <div className="opening-row" key={i}>
            <select className="input wide" value={l.code} disabled={readOnly} aria-label={`Account ${i + 1}`}
                    onChange={e => setLine(i, { code: e.target.value })}>
              {optionsFor(l.code).map(a => <option key={a.code} value={a.code}>{a.name ? `${a.code} ${a.name}` : a.code}</option>)}
            </select>
            <input className="input num" inputMode="decimal" placeholder="Debit £" aria-label={`Account ${i + 1} debit`}
                   value={l.debit} readOnly={readOnly} onChange={e => setLine(i, { debit: e.target.value })} />
            <input className="input num" inputMode="decimal" placeholder="Credit £" aria-label={`Account ${i + 1} credit`}
                   value={l.credit} readOnly={readOnly} onChange={e => setLine(i, { credit: e.target.value })} />
            {!readOnly && (
              <button type="button" className="link-btn danger" onClick={() => { changed(); setLines(ls => ls.filter((_, j) => j !== i)) }}>
                Remove
              </button>
            )}
          </div>
        ))}
      </div>
      {!readOnly && <button type="button" className="btn btn-small add-btn" onClick={addLine}>Add account</button>}

      <h3>Unpaid invoices</h3>
      <p className="muted small">List the invoices behind Debtors and Creditors so payments can clear each. Any you leave out are brought
        forward as one balance, &ldquo;Not itemised&rdquo;, which a payment can still be linked to.</p>
      {!items.length && <p className="muted">No unpaid invoices.</p>}
      <div className="opening-rows">
        {items.map((x, i) => (
          <div className="opening-row invoice" key={x.id}>
            <select className="input wide" value={x.direction} disabled={readOnly} aria-label={`Unpaid invoice ${i + 1} owed`}
                    onChange={e => setItem(i, { direction: e.target.value as 'in' | 'out' })}>
              <option value="in">A customer owes the client</option>
              <option value="out">The client owes a supplier</option>
            </select>
            <input className="input wide" placeholder={x.direction === 'in' ? 'Customer' : 'Supplier'} aria-label={`Unpaid invoice ${i + 1} name`}
                   value={x.counterparty} readOnly={readOnly} onChange={e => setItem(i, { counterparty: e.target.value })} />
            <input className="input" placeholder="Number" aria-label={`Unpaid invoice ${i + 1} number`}
                   value={x.number} readOnly={readOnly} onChange={e => setItem(i, { number: e.target.value })} />
            <input className="input" type="date" aria-label={`Unpaid invoice ${i + 1} date`}
                   value={x.date} readOnly={readOnly} onChange={e => setItem(i, { date: e.target.value })} />
            <input className="input num" inputMode="decimal" placeholder="Owed £" aria-label={`Unpaid invoice ${i + 1} amount owed`}
                   value={x.amount} readOnly={readOnly} onChange={e => setItem(i, { amount: e.target.value })} />
            {!readOnly && (
              <button type="button" className="link-btn danger" onClick={() => { changed(); setItems(is => is.filter((_, j) => j !== i)) }}>
                Remove
              </button>
            )}
          </div>
        ))}
      </div>
      {!readOnly && (
        <div className="add-btns">
          <button type="button" className="btn btn-small" onClick={() => addItem('in')}>Add customer invoice</button>
          <button type="button" className="btn btn-small" onClick={() => addItem('out')}>Add supplier bill</button>
        </div>
      )}

      {!readOnly && touched && problems.length > 0 && (
        <div className="notice notice-warn"><span>{problems.map(p => <span key={p} className="problem">{p}</span>)}</span></div>
      )}
      {error && <div className="notice notice-error">{error}</div>}
      {saved && <div className="notice notice-info">Opening balances saved.</div>}
      {!readOnly && (
        <div className="dialog-actions">
          <button type="button" className="btn btn-primary" onClick={save} disabled={saving || problems.length > 0}>
            {saving ? 'Saving…' : 'Save opening balances'}
          </button>
        </div>
      )}
    </section>
  )
}
