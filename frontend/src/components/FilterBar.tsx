'use client'

import { useState } from 'react'
import { DOCUMENT_TYPES } from '@/lib/clientRules'
import { filterChips, needsReviewLabel, NO_FILTERS, type ReviewItem, type RowFilters } from '@/lib/ledger'

// Narrowing the Transactions table, on one line: words, a Filters button opening the rest (account, kind of document,
// direction, state, dates, amounts), and what needs review, by kind. Under it, each filter set as a chip that clears
// it, and how many rows are shown.
export default function FilterBar({ filters, onFilters, review, only, onOnly, flaggedRows, flaggedDocuments, accounts, types, shown, total }: {
  filters: RowFilters
  onFilters: (f: RowFilters) => void
  review: ReviewItem[]                   // the kinds of issue, with their rows, errors first
  only: string | null                    // the review picked: an issue code, 'review' for every flagged row, or none
  onOnly: (code: string | null) => void
  flaggedRows: number                    // rows that need review
  flaggedDocuments: number               // documents with a problem of their own
  accounts: [string, string][]           // the accounts the rows are on: code, name
  types: string[]                        // the kinds of document the rows came from
  shown: number                          // rows the table lists, filters and review pick together
  total: number
}) {
  const [open, setOpen] = useState(false)
  const set = (field: keyof RowFilters, value: string) => onFilters({ ...filters, [field]: value })
  const names = {
    account: (code: string) => accounts.find(([c]) => c === code)?.[1] ?? code,
    type: (t: string) => DOCUMENT_TYPES[t] ?? t,
  }
  const chips = filterChips(filters, names)
  const more = chips.filter(c => c.field !== 'text').length
  const flagged = flaggedRows + flaggedDocuments
  // The review picked is a chip too, so Clear and × undo it like any filter.
  const picked = only === null ? null : only === 'review' ? 'Needs review' : review.find(r => r.code === only)?.title ?? only
  const count = (n: number) => n.toLocaleString('en-GB')
  const clear = (field: keyof RowFilters | 'dates' | 'amounts') =>
    onFilters(field === 'dates' ? { ...filters, from: '', to: '' }
      : field === 'amounts' ? { ...filters, min: '', max: '' } : { ...filters, [field]: '' })

  return (
    <div className="filters" role="search" aria-label="Filter transactions">
      <div className="filter-line">
        <input className="input filter-text" type="search" value={filters.text} aria-label="Search"
               placeholder="Search description, supplier, file or account" onChange={e => set('text', e.target.value)} />
        <button type="button" className={`btn btn-small${more ? ' btn-on' : ''}`} aria-expanded={open}
                onClick={() => setOpen(o => !o)}>
          Filters{more ? ` · ${more}` : ''}
        </button>
        {flagged > 0 && (
          <select className="input filter-review" aria-label="Needs review" value={only ?? ''}
                  onChange={e => onOnly(e.target.value || null)}>
            <option value="">All rows</option>
            <option value="review">{needsReviewLabel(flaggedRows, flaggedDocuments)}</option>
            {review.map(item => (
              <option key={item.code} value={item.code}>{item.severity === 'error' ? '✖ ' : ''}{item.title} · {item.rows}</option>
            ))}
          </select>
        )}
      </div>
      {open && (
        <div className="filter-panel">
          <label>Account
            <select className="input" value={filters.account} onChange={e => set('account', e.target.value)}>
              <option value="">All accounts</option>
              {accounts.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          </label>
          <label>Document
            <select className="input" value={filters.type} onChange={e => set('type', e.target.value)}>
              <option value="">All types</option>
              {types.map(type => <option key={type} value={type}>{DOCUMENT_TYPES[type] ?? type}</option>)}
            </select>
          </label>
          <label>Money
            <select className="input" value={filters.direction} onChange={e => set('direction', e.target.value)}>
              <option value="">In and out</option>
              <option value="out">Money out</option>
              <option value="in">Money in</option>
            </select>
          </label>
          <label>State
            <select className="input" value={filters.status} onChange={e => set('status', e.target.value)}>
              <option value="">Any state</option>
              <option value="review">To review</option>
              <option value="edited">Edited</option>
              <option value="vat">With VAT</option>
              <option value="no_vat">No VAT</option>
              <option value="not_booked">Not booked</option>
            </select>
          </label>
          <label>From
            <input className="input" type="date" value={filters.from} onChange={e => set('from', e.target.value)} />
          </label>
          <label>To
            <input className="input" type="date" value={filters.to} onChange={e => set('to', e.target.value)} />
          </label>
          <label>£ from
            <input className="input" inputMode="decimal" value={filters.min} placeholder="0.00" onChange={e => set('min', e.target.value)} />
          </label>
          <label>£ to
            <input className="input" inputMode="decimal" value={filters.max} placeholder="any" onChange={e => set('max', e.target.value)} />
          </label>
        </div>
      )}
      {(chips.length > 0 || picked) && (
        <div className="filter-chips">
          {picked && (
            <button type="button" className="filter-chip" aria-label={`Clear ${picked}`} onClick={() => onOnly(null)}>
              {picked} <span aria-hidden="true">×</span>
            </button>
          )}
          {chips.map(chip => (
            <button key={chip.field} type="button" className="filter-chip" aria-label={`Clear ${chip.label}`}
                    onClick={() => clear(chip.field)}>
              {chip.label} <span aria-hidden="true">×</span>
            </button>
          ))}
          <span className="muted small">{count(shown)} of {count(total)} shown</span>
          <button type="button" className="link-btn small" onClick={() => { onFilters(NO_FILTERS); onOnly(null) }}>Clear</button>
        </div>
      )}
    </div>
  )
}
