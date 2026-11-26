'use client'

import Link from 'next/link'
import type { Issue } from '@/lib/api'
import type { AccountChoice, RowChange } from '@/lib/clients'
import { aboutAnotherRow, acceptLabel, canBeAccepted, canBeApart, issueHeading, showLabel, type IssueFix } from '@/lib/ledger'

const SEVERITY_ORDER = { error: 0, warning: 1, info: 2 } as const
export const MARKS = { error: '✖', warning: '⚠', info: 'ℹ' } as const

// What is wrong with a row, in words, under its description: errors first, then warnings, then notes. Each warning
// or error carries its own way out: the fix where there is one (a change made at once, the accounts to choose from,
// Edit, or Documents for a missing file), Show both and Not the same for two records that may be one, It's fine for
// a matter of judgement, and Ask the AI, which opens a chat on the issue.
export default function IssueList({ issues, onShowBoth, onNotSame, onAccept, fixesOf, onFix, onEdit, onAddLine, accounts, documentsHref, askHref }: {
  issues: Issue[]
  onShowBoth?: (related: number[]) => void   // each issue shows the rows it is about
  onNotSame?: (related: number[]) => void
  onAccept?: (code: string) => void          // a warning that is a matter of judgement: the person says it is fine
  fixesOf?: (issue: Issue) => IssueFix[]     // none when the row can't be changed
  onFix?: (change: RowChange) => void
  onEdit?: () => void
  onAddLine?: () => void                     // a document's problem: add the line its total is short of
  accounts?: AccountChoice[]                 // the accounts a row of the client can be coded to
  documentsHref?: string
  askHref?: (issue: Issue) => string         // the chat, asked about the issue
}) {
  if (!issues.length) return null
  const sorted = [...issues].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
  return (
    <ul className="issues">
      {sorted.map((issue, k) => (
        <li key={k} className={`issue issue-${issue.severity}`}>
          <span className="issue-mark" aria-hidden="true">{MARKS[issue.severity]}</span>
          <span>
            <strong>{issueHeading(issue.code)}</strong> {issue.message}
            <span className="issue-actions">
            {onShowBoth && aboutAnotherRow(issue.code) && !!issue.related?.length && (
              <button type="button" className="link-btn" onClick={() => onShowBoth(issue.related!)}>
                {showLabel(issue.code)}
              </button>
            )}
            {onNotSame && canBeApart(issue.code) && !!issue.related?.length && (
              <button type="button" className="link-btn" onClick={() => onNotSame(issue.related!)}>Not the same</button>
            )}
            {onAddLine && issue.severity !== 'info' && (
              <button type="button" className="link-btn" onClick={onAddLine}>Add line</button>
            )}
            {(fixesOf?.(issue) ?? []).map((fix, j) => (
              fix.change && onFix ? (
                <button key={j} type="button" className="link-btn" onClick={() => onFix(fix.change!)}>{fix.label}</button>
              ) : fix.choose === 'account' && onFix ? (
                <select key={j} className="input issue-choice" value="" aria-label={fix.label}
                        onChange={e => { if (e.target.value) onFix({ account_code: e.target.value }) }}>
                  <option value="">{accounts?.length ? `${fix.label}…` : 'Loading the accounts…'}</option>
                  {(accounts ?? []).map(a => <option key={a.code} value={a.code}>{a.name}</option>)}
                </select>
              ) : fix.edit && onEdit ? (
                <button key={j} type="button" className="link-btn" onClick={onEdit}>{fix.label}</button>
              ) : fix.documents && documentsHref ? (
                <Link key={j} className="link-btn" href={documentsHref}>{fix.label}</Link>
              ) : null
            ))}
            {onAccept && issue.severity === 'warning' && canBeAccepted(issue.code) && (
              <button type="button" className="link-btn" onClick={() => onAccept(issue.code)}>{acceptLabel(issue.code)}</button>
            )}
            {askHref && issue.severity !== 'info' && (
              <Link className="link-btn" href={askHref(issue)}>Ask the AI</Link>
            )}
            </span>
          </span>
        </li>
      ))}
    </ul>
  )
}
