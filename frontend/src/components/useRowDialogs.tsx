'use client'

import { useState, type ReactNode } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import EditRowDialog from '@/components/EditRowDialog'
import type { Transaction } from '@/lib/api'
import { addManualRows, changeRow, type RowChange, type SavedRow } from '@/lib/clients'
import { lineTemplate, newRowFrom, type EditDraft } from '@/lib/clientRules'

// Edit a row, or add one (a transaction of its own, or a line of a row's document), in a dialog: the same two
// dialogs wherever a row can be edited, so Edit and Add line do one thing on every page. The year's ledger is shown
// as the API returns it. Render `dialogs` once in the page.
export function useRowDialogs(): { edit: (row: SavedRow) => void; add: (lineOf: SavedRow | null) => void; dialogs: ReactNode } {
  const { client, year, show } = useClientYear()
  const [editing, setEditing] = useState<SavedRow | null>(null)
  const [adding, setAdding] = useState<{ template: Transaction; title: string } | null>(null)   // a row being added
  const add = (lineOf: SavedRow | null) => setAdding({
    template: lineTemplate(lineOf),
    title: lineOf ? `Add a line to ${lineOf.counterparty ?? 'this document'}` : 'Add a transaction',
  })
  const saveNew = async (draft: EditDraft) => {
    if (!adding) return
    const next = await addManualRows(client.id, [newRowFrom(draft, adding.template)], year.start)
    setAdding(null)
    show(next)
  }
  const saveRow = async (change: RowChange) => {   // the dialog shows its own Saving… and any error
    if (!editing) return
    const next = await changeRow(client.id, editing.id, change)
    setEditing(null)
    show(next)
  }
  const dialogs = (
    <>
      {editing && (
        <EditRowDialog row={editing} client={client} onCancel={() => setEditing(null)} onSave={saveRow} />
      )}
      {adding && (
        <EditRowDialog row={adding.template} client={client} title={adding.title}
                       onCancel={() => setAdding(null)} onAdd={saveNew} />
      )}
    </>
  )
  return { edit: setEditing, add, dialogs }
}
