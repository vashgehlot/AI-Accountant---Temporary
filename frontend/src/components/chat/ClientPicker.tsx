'use client'

import { useMemo, useState } from 'react'
import { searchClients } from '@/lib/clientRules'
import type { ClientSummary } from '@/lib/clients'

// "Which client are we working on?": a search box and a chip per client. Picking one makes no model call.
export default function ClientPicker({ clients, busy, onPick }: {
  clients: ClientSummary[]
  busy: boolean
  onPick: (client: ClientSummary) => void
}) {
  const [query, setQuery] = useState('')
  const shown = useMemo(() => searchClients(clients, query), [clients, query])
  return (
    <div className="client-picker">
      <h1>Which client are we working on?</h1>
      <input className="input search" type="search" value={query} onChange={e => setQuery(e.target.value)}
             placeholder="Search clients" aria-label="Search clients" autoFocus />
      <div className="client-chips">
        {shown.map(c => (
          <button key={c.id} type="button" className="chip client-chip" disabled={busy} onClick={() => onPick(c)}>
            {c.name}
          </button>
        ))}
        {!shown.length && <p className="muted small">No clients match your search.</p>}
      </div>
    </div>
  )
}
