'use client'

import DecisionLine from '@/components/chat/DecisionLine'
import type { Decision } from '@/lib/chat'
import type { ActivityLine, AiChange } from '@/lib/reviews'

// What has already happened, below the list and closed until asked for: every change a review made that still
// stands, each with Undo (and the changes the person applied on this visit, which open the list so they can be
// taken back); and one line for each run.
export default function ReviewHistory({ changes, made, lines, readOnly, working, refused, onUndo }: {
  changes: AiChange[]
  made: Decision[]                     // applied from the list since the page opened
  lines: ActivityLine[]
  readOnly: boolean
  working: string                      // the change being undone, if any
  refused: Record<string, string>      // why an Undo didn't go through, by decision
  onUndo: (d: Decision) => void
}) {
  const fresh = changes.filter(c => c.fresh).length
  const all = [...made, ...changes.map(c => c.decision)]
  return (
    <div className="review-history">
      {all.length > 0 && (
        <details open={made.length > 0 || undefined}>
          <summary>
            Changed by the AI <span className="review-count">{all.length}</span>
            {fresh > 0 && <span className="muted small"> · {fresh} new since you last looked</span>}
          </summary>
          {all.map(d => (
            <div key={d.id} className="review-change">
              <ul className="decisions"><DecisionLine decision={d} /></ul>
              <div className="question-row">
                <button type="button" className="btn btn-small" disabled={readOnly || !!working} onClick={() => onUndo(d)}>
                  {working === d.id ? 'Undoing…' : 'Undo'}
                </button>
                {refused[d.id] && <span className="field-error">{refused[d.id]}</span>}
              </div>
            </div>
          ))}
        </details>
      )}
      {lines.length > 0 && (
        <details>
          <summary>Activity</summary>
          <ul>
            {lines.map(line => <li key={line.key} className={line.failed ? 'field-error small' : 'muted small'}>{line.text}</li>)}
          </ul>
        </details>
      )}
    </div>
  )
}
