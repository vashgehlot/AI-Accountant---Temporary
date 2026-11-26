'use client'

import { useState } from 'react'
import { formatMoney, shownAccounts, suspenseLabel, SUSPENSE, type PostedTrialBalance as Posted } from '@/lib/chat'

const amount = (s: string) => (Number(s) === 0 ? '' : formatMoney(s))

// The posted ledger's trial balance: balanced or not, the first accounts with Suspense and what each item in it
// needs, and the whole table on request.
export default function PostedTrialBalance({ tb }: { tb: Posted }) {
  const [all, setAll] = useState(false)
  const { shown, more } = shownAccounts(tb)
  const lines = all ? tb.lines.filter(l => Number(l.debit) !== 0 || Number(l.credit) !== 0) : shown
  const held = tb.suspense.length
  return (
    <div className="posted">
      <p>
        <strong>Posted.</strong>{' '}
        <span className={tb.is_balanced ? 'badge badge-accent' : 'badge badge-warn'}>
          {tb.is_balanced ? 'Balanced' : 'Not balanced'}
        </span>
        {held > 0 && <span className="muted small"> {held} {held === 1 ? 'item' : 'items'} in Suspense</span>}
      </p>
      {tb.problems.length > 0 && <p className="text-error small">{tb.problems.join(' ')}</p>}
      {tb.unposted_changes > 0 && (
        <p className="text-warn small">
          {tb.unposted_changes} {tb.unposted_changes === 1 ? 'change' : 'changes'} not posted
        </p>
      )}
      <div className="table-card posted-table">
        <table className="table">
          <thead><tr><th>Account</th><th className="num">Debit</th><th className="num">Credit</th></tr></thead>
          <tbody>
            {lines.map(l => (
              <tr key={l.code} className={l.code === SUSPENSE ? 'suspense-line' : undefined}>
                <td>
                  <span className="mono">{l.code}</span> {l.name}
                  {l.code === SUSPENSE && tb.suspense.map(item => (
                    <span key={item.row_id} className="suspense-item">
                      {item.description} · {formatMoney(item.gross)}{' '}
                      <span className={item.needs ? 'badge badge-warn' : 'badge badge-muted'}>{suspenseLabel(item.needs)}</span>
                    </span>
                  ))}
                </td>
                <td className="num">{amount(l.debit)}</td>
                <td className="num">{amount(l.credit)}</td>
              </tr>
            ))}
          </tbody>
          {all && (
            <tfoot>
              <tr><td>Total</td><td className="num">{formatMoney(tb.total_debits)}</td><td className="num">{formatMoney(tb.total_credits)}</td></tr>
            </tfoot>
          )}
        </table>
      </div>
      {(more > 0 || all) && (
        <button type="button" className="link-btn posted-more" onClick={() => setAll(a => !a)}>
          {all ? 'Show fewer accounts' : `… ${more} more ${more === 1 ? 'account' : 'accounts'} · open the full trial balance`}
        </button>
      )}
    </div>
  )
}
