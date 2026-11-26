'use client'

import { useEffect, useRef, useState } from 'react'
import type { Issue } from '@/lib/api'
import { changedFields, type Decision } from '@/lib/chat'
import { useClientYear } from '@/components/ClientYearContext'
import { OneDocument } from '@/components/DocumentPanel'
import IssueList from '@/components/IssueList'
import type { AccountChoice, RowChange, SavedRow, Upload } from '@/lib/clients'
import { DOCUMENT_TYPES } from '@/lib/clientRules'
import { sectionHref } from '@/lib/years'
import {
  acceptChange, accountName, apartChange, apartStatus, askAbout, capActions, claimLineOf, issueFixes, leftOut, leftOutLabel,
  longDate, money, netBooked, rowStatus, signedAmount, takesLines, vatBooked, type DocumentProblem, type RowStatus,
} from '@/lib/ledger'

// A document with more lines than this opens closed in the panel: a bank statement's hundreds would bury the rest.
const MANY_LINES = 12

// A row's VAT treatment, when a person chose one.
const VAT_SHORT: Record<string, string> = { standard: '20%', reduced: '5%', zero: 'Zero-rated', exempt: 'Exempt',
                                            outside_scope: 'Outside scope' }

const FIELD_NAMES: Record<string, string> = {
  date: 'date', description: 'description', counterparty: 'counterparty', direction: 'in/out', gross: 'amount',
  vat: 'VAT', account_code: 'account', document_type: 'type', currency: 'currency',
  vat_treatment: 'VAT treatment',
}

// The hover on an edited row: what the model read, where it differs from now.
function originalText(row: SavedRow): string {
  const now = row as unknown as Record<string, string | null | undefined>
  const changed = Object.entries(row.original ?? {})
    .filter(([field, value]) => (value ?? '') !== (now[field] ?? ''))
    .map(([field, value]) => `${FIELD_NAMES[field] ?? field} ${field === 'gross' || field === 'vat' ? money(value) : value || 'none'}`)
  return changed.length ? `Read by the model: ${changed.join(', ')}` : 'Edited'
}

// The decisions that touched a row: the rule, what it was based on, and what changed.
function AgentDecisions({ decisions }: { decisions: Decision[] }) {
  return (
    <details className="small agent-decisions">
      <summary className="badge badge-accent">Agent</summary>
      {decisions.map(d => (
        <div key={d.id}>
          <strong>{d.rule}</strong>{d.status === 'refused' && ' (refused)'}
          <div className="muted">{d.trigger === 'background' ? 'From a background review' : 'From a chat'}</div>
          {d.reason && <div>{d.reason}</div>}
          {d.evidence.map((e, k) => <div key={k} className="muted">{e.upload_name}: “{e.quote}”</div>)}
          {changedFields(d).map((c, k) => (
            <div key={k} className="muted">Row {c.row} {c.field}: {c.before} → {c.after}</div>
          ))}
        </div>
      ))}
    </details>
  )
}

// One status line with its choices: the first three as buttons, the rest (a payout that may be any of 45
// statements) in one picker.
function StatusLine({ status, row, readOnly, onChange }: {
  status: RowStatus; row: SavedRow; readOnly: boolean; onChange: (rowId: number, change: RowChange) => void
}) {
  if (status.include !== undefined) {
    return (
      <label className="row-status">
        <input type="checkbox" checked={status.include} disabled={readOnly}
               onChange={e => onChange(row.id, { include: e.target.checked })} />
        {status.text}
      </label>
    )
  }
  const { shown, rest } = capActions(status.actions)
  return (
    <div className="row-status">
      {status.text}
      {!readOnly && (
        <span className="issue-actions">
          {shown.map((action, j) => (
            <button key={j} type="button" className="link-btn" onClick={() => onChange(action.row ?? row.id, action.change)}>
              {action.label}
            </button>
          ))}
          {rest.length > 0 && (
            <select className="input issue-choice" value="" aria-label="Link to another"
                    onChange={e => { const action = rest[Number(e.target.value)]; if (action) onChange(action.row ?? row.id, action.change) }}>
              <option value="">Link to another… ({rest.length})</option>
              {rest.map((action, j) => <option key={j} value={j}>{action.label}</option>)}
            </select>
          )}
        </span>
      )}
    </div>
  )
}

// Everything about one row, beside the table: what is wrong with it and its fixes, its status and choices, its
// figures, who changed it, its document, and Edit, Add line, Revert and Remove. A closed year or an archived client
// shows it with no control that changes anything.
export default function RowPanel({ row, issues, documentProblems, rows, uploads, decisions, held, whyLeftOut, readOnly,
                                   accounts, onChange, onEdit, onAdd, onRemove, onShowTogether, onClose }: {
  row: SavedRow
  issues: Issue[]                               // the row's own, a possible duplicate among them
  documentProblems: DocumentProblem<SavedRow>[] // problems with the whole document the row is a line of
  rows: SavedRow[]
  uploads: Upload[]
  decisions: Decision[] | null                  // the agent's decisions on the row; null: some, not loaded
  held: boolean                                 // waiting in Suspense for its document
  whyLeftOut: string | null
  readOnly: boolean
  accounts: AccountChoice[]
  onChange: (rowId: number, change: RowChange) => void
  onEdit?: (row: SavedRow) => void
  onAdd?: (lineOf: SavedRow | null) => void
  onRemove?: (row: SavedRow) => void
  onShowTogether: (ids: number[]) => void
  onClose: () => void
}) {
  const { client, year } = useClientYear()
  const [without, setWithout] = useState<string | null>(null)   // the reason being typed for booking without a receipt
  // The panel takes the focus when it opens, so the keyboard carries on in it.
  const panel = useRef<HTMLElement>(null)
  useEffect(() => { panel.current?.focus({ preventScroll: true }) }, [])
  const left = leftOut(row)
  const amount = signedAmount(row)
  const upload = uploads.find(u => u.id === row.upload_id)
  const type = DOCUMENT_TYPES[row.document_type ?? 'receipt'] ?? row.document_type
  const byId = new Map(rows.map(r => [r.id, r]))
  const lines = upload ? rows.filter(r => r.upload_id === upload.id) : []
  const statuses = [...rowStatus(row, id => byId.get(id)),
                    ...[apartStatus(row, id => byId.get(id)?.description)].filter(s => s !== null)]
  const askHref = (on: SavedRow) => (issue: Issue) => `/chat?client=${client.id}&ask=${encodeURIComponent(askAbout(on, issue))}`

  return (
    <aside ref={panel} tabIndex={-1} className="row-panel" aria-label={`Row: ${row.description}`}>
      <div className="row-panel-head">
        <div>
          <strong style={left ? { textDecoration: 'line-through' } : undefined}>{row.description}</strong>
          <div className="muted small">
            {row.date ? longDate(row.date) : 'No date'} · <span className={`mono amount-${amount.tone}`}>{amount.text.replace(/^([+\u2212]?)/, '$1£')}</span>
          </div>
          <div className="muted small">{upload?.name ?? 'Typed in'} · {type}</div>
        </div>
        <button type="button" className="btn btn-small" onClick={onClose} aria-label="Close the row">Close</button>
      </div>

      {left && (
        <div className="row-status">{leftOutLabel(row)}{!row.removed && whyLeftOut && `: ${whyLeftOut}`}
          {row.removed && !readOnly && (
            <button type="button" className="link-btn" title="Book it again" onClick={() => onChange(row.id, { removed: false })}>
              Put back
            </button>
          )}
        </div>
      )}

      {/* A row out of the books needs nothing: what was wrong with it stays readable, muted, with no fix. */}
      <div className={left ? 'issues-muted' : undefined}>
      <IssueList issues={issues.filter(i => i.code !== 'booked_without_document')}
                 onShowBoth={related => onShowTogether([row.id, ...related])}
                 onNotSame={readOnly || left ? undefined : related => onChange(row.id, apartChange(row, related))}
                 onAccept={readOnly || left ? undefined : code => onChange(row.id, acceptChange(row, code))}
                 fixesOf={readOnly || left ? undefined : issue => issueFixes(row, issue, claimLineOf(row, rows))}
                 onFix={change => onChange(row.id, change)} onEdit={onEdit ? () => onEdit(row) : undefined}
                 accounts={accounts} documentsHref={sectionHref(client.id, year.start, 'documents')}
                 askHref={readOnly || left ? undefined : askHref(row)} />
      </div>
      {documentProblems.map(({ row: first, issue, lines }) => (
        <IssueList key={`${first.id}:${issue.code}`} issues={[issue]} onShowBoth={() => onShowTogether(lines)}
                   onAddLine={!readOnly && onAdd && takesLines(first) ? () => onAdd(first) : undefined}
                   fixesOf={readOnly ? undefined : found => issueFixes(first, found)}
                   onFix={change => onChange(first.id, change)}
                   askHref={readOnly ? undefined : askHref(first)} />
      ))}

      {(statuses.length > 0 || held || without !== null) && (
        <div className="row-panel-part">
          {statuses.map((status, k) => <StatusLine key={k} status={status} row={row} readOnly={readOnly} onChange={onChange} />)}
          {held && !row.issues.some(i => i.code === 'booked_without_document') && (
            <div className="row-status">
              <span className="badge badge-warn">Documentation required</span>
              {!readOnly && without === null && (
                <button type="button" className="link-btn" title="Book it to its account with no VAT reclaimed"
                        onClick={() => setWithout('')}>Book without a receipt</button>
              )}
            </div>
          )}
          {without !== null && (
            <form className="row-status without-form" onSubmit={e => {
              e.preventDefault()
              if (!without.trim()) return
              onChange(row.id, { without_document: without.trim() })
              setWithout(null)
            }}>
              <input className="input" value={without} maxLength={300} autoFocus aria-label="Why there is no receipt or invoice"
                     placeholder="Why there is none, e.g. receipt lost" onChange={e => setWithout(e.target.value)} />
              <button type="submit" className="btn btn-primary btn-small" disabled={!without.trim()}>Book with no VAT</button>
              <button type="button" className="btn btn-small" onClick={() => setWithout(null)}>Cancel</button>
            </form>
          )}
        </div>
      )}

      <dl className="row-figures">
        <div><dt>{row.document_type === 'journal' ? 'Journal' : row.direction === 'in' ? 'Money in' : 'Money out'}</dt>
             <dd className="mono">{money(row.gross)}</dd></div>
        <div><dt>VAT{row.vat_treatment ? ` (${VAT_SHORT[row.vat_treatment] ?? row.vat_treatment})` : ''}</dt>
          <dd className="mono">{money(vatBooked(row))}
            {row.vat_not_reclaimed && (
              <div className="muted small" title={row.vat_not_reclaimed_why ?? undefined}>
                {money(row.vat_not_reclaimed)} not reclaimed
                {!readOnly && !left && (
                  <button type="button" className="link-btn" title="Reclaim this VAT on your say: you hold the VAT invoice"
                          onClick={() => onChange(row.id, { vat_confirmed: true })}>Reclaim it</button>
                )}
              </div>
            )}
          </dd></div>
        <div><dt>Net</dt><dd className="mono">{money(netBooked(row))}</dd></div>
        <div><dt>Account</dt><dd>{accountName(row)}</dd></div>
      </dl>
      {(row.edited || decisions !== null && decisions.length > 0 || decisions === null) && (
        <div className="row-panel-part">
          {row.edited && <span className="badge badge-muted edited" title={originalText(row)}>Edited</span>}
          {row.edited && <span className="muted small"> {originalText(row)}</span>}
          {decisions === null ? <span className="badge badge-accent">Agent</span>
            : decisions.length > 0 && <AgentDecisions decisions={decisions} />}
        </div>
      )}

      {!readOnly && !left && (
        <div className="row-panel-actions">
          {onEdit && <button type="button" className="btn btn-small" onClick={() => onEdit(row)}>Edit</button>}
          {onAdd && takesLines(row) && <button type="button" className="btn btn-small" onClick={() => onAdd(row)}>Add line</button>}
          {row.edited && <button type="button" className="btn btn-small" onClick={() => onChange(row.id, { revert: true })}>Revert</button>}
          {onRemove && !row.removed && (
            <button type="button" className="btn btn-small danger" onClick={() => onRemove(row)}>Remove</button>
          )}
        </div>
      )}

      {/* The document it was read from: open at once unless it is a long list of lines, such as a bank statement. */}
      {upload && (
        <details className="row-panel-part row-panel-document" open={lines.length <= MANY_LINES}>
          <summary className="muted small">Document · {upload.name}{lines.length > 1 ? ` · ${lines.length} lines` : ''}</summary>
          <OneDocument clientId={client.id} doc={{ upload, rowId: row.id, quotes: [], rows: lines }} />
        </details>
      )}
    </aside>
  )
}
