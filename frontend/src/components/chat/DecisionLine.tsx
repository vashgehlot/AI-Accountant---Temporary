'use client'

import Link from 'next/link'
import { useState } from 'react'
import { changedFields, ruleBadge, type Decision } from '@/lib/chat'
import { sectionHref } from '@/lib/years'

// One thing sorted: the rule and why. Clicking it opens before → after, the evidence quotes with their original
// files, and the way to the rows in Transactions.
export default function DecisionLine({ decision }: { decision: Decision }) {
  const [open, setOpen] = useState(false)
  const badge = ruleBadge(decision)
  const title = badge ? decision.rule.slice(badge.length).trim() : decision.rule
  const changes = changedFields(decision)
  return (
    <li className="decision">
      <button type="button" className="decision-head" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="decision-caret" aria-hidden="true" />
        {badge && <span className="badge badge-accent mono">{badge}</span>}
        <span className="decision-text">
          <strong>{title}</strong>{decision.reason && <> · {decision.reason}</>}
        </span>
      </button>
      {open && (
        <div className="decision-body">
          {changes.length > 0 && (
            <table className="table decision-changes">
              <thead><tr><th>Row</th><th>Field</th><th>Before</th><th aria-label="to" /><th>After</th></tr></thead>
              <tbody>
                {changes.map(c => (
                  <tr key={`${c.row}-${c.field}`}>
                    <td className="mono muted">{c.row}</td>
                    <td>{c.field}</td>
                    <td className="mono">{c.before}</td>
                    <td className="muted" aria-hidden="true">→</td>
                    <td className="mono">{c.after}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {decision.evidence.map((e, i) => (
            <blockquote key={i} className="evidence">
              <p>“{e.quote}”</p>
              <a href={`/api/clients/${decision.client_id}/uploads/${e.upload_id}/file`} target="_blank" rel="noreferrer"
                 className="small">{e.upload_name || 'Original file'}</a>
            </blockquote>
          ))}
          <Link href={sectionHref(decision.client_id, decision.year_start, 'transactions')} className="small">
            View in Transactions
          </Link>
        </div>
      )}
    </li>
  )
}
