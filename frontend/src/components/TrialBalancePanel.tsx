'use client'

import { useEffect, useState } from 'react'
import type { TrialBalanceResult } from '@/lib/api'
import { clientTrialBalance } from '@/lib/clients'
import { money } from '@/lib/ledger'

// The client's trial balance from its saved rows. A change to the rows clears one already shown.
export default function TrialBalancePanel({ clientId, version, hasRows }: {
  clientId: number
  version: number
  hasRows: boolean
}) {
  const [result, setResult] = useState<TrialBalanceResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { setResult(null); setError('') }, [version])

  const generate = async () => {
    setBusy(true)
    setError('')
    try {
      setResult(await clientTrialBalance(clientId))
    } catch (e) {
      setResult(null)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const apart = result ? Math.abs(Number(result.total_debits) - Number(result.total_credits)) : 0
  const netProfit = result?.net_profit ? Number(result.net_profit) : 0

  return (
    <section className="card section">
      <div className="section-head">
        <h2>Trial balance & Financial Summary</h2>
        <button type="button" className="btn" onClick={generate} disabled={busy || !hasRows}>
          {busy ? <><span className="spinner" aria-hidden="true" /> Generating...</> : 'Generate trial balance'}
        </button>
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      {result && (
        <>
          <div className="tb-summary-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px', marginBottom: '16px' }}>
            <div className="tb-card" style={{ padding: '10px 12px', background: 'var(--surface-color, #1e293b)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }}>
              <div style={{ fontSize: '11px', textTransform: 'uppercase', opacity: 0.7 }}>Net Profit / Loss</div>
              <div style={{ fontSize: '16px', fontWeight: 'bold', color: netProfit >= 0 ? '#10b981' : '#f43f5e', marginTop: '2px' }}>
                {money(result.net_profit ?? '0.00')}
              </div>
            </div>
            <div className="tb-card" style={{ padding: '10px 12px', background: 'var(--surface-color, #1e293b)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }}>
              <div style={{ fontSize: '11px', textTransform: 'uppercase', opacity: 0.7 }}>Total Income</div>
              <div style={{ fontSize: '16px', fontWeight: 'bold', color: '#10b981', marginTop: '2px' }}>
                {money(result.total_income ?? '0.00')}
              </div>
            </div>
            <div className="tb-card" style={{ padding: '10px 12px', background: 'var(--surface-color, #1e293b)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }}>
              <div style={{ fontSize: '11px', textTransform: 'uppercase', opacity: 0.7 }}>Total Expenses</div>
              <div style={{ fontSize: '16px', fontWeight: 'bold', color: '#6366f1', marginTop: '2px' }}>
                {money(result.total_expenses ?? '0.00')}
              </div>
            </div>
            <div className="tb-card" style={{ padding: '10px 12px', background: 'var(--surface-color, #1e293b)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }}>
              <div style={{ fontSize: '11px', textTransform: 'uppercase', opacity: 0.7 }}>Assets / Liabilities</div>
              <div style={{ fontSize: '13px', fontWeight: '600', marginTop: '2px' }}>
                {money(result.total_assets ?? '0.00')} / {money(result.total_liabilities ?? '0.00')}
              </div>
            </div>
          </div>

          <table className="table">
            <thead><tr><th>Account</th><th>Type</th><th className="num">Debit</th><th className="num">Credit</th></tr></thead>
            <tbody>
              {result.lines.map(line => (
                <tr key={line.code}>
                  <td><span className="mono">{line.code}</span> {line.name}</td>
                  <td><span className="badge" style={{ fontSize: '10px', padding: '1px 5px', textTransform: 'uppercase' }}>{line.type}</span></td>
                  <td className="num">{Number(line.debit) > 0 ? money(line.debit) : '—'}</td>
                  <td className="num">{Number(line.credit) > 0 ? money(line.credit) : '—'}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2}>Totals</td>
                <td className="num">{money(result.total_debits)}</td>
                <td className="num">{money(result.total_credits)}</td>
              </tr>
            </tfoot>
          </table>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '12px' }}>
            <span className={`badge tb-pill ${result.is_balanced ? 'badge-accent' : 'badge-warn'}`}>
              {result.is_balanced ? 'Debits equal credits' : `Out of balance by £${apart.toFixed(2)}`}
            </span>
          </div>
        </>
      )}
    </section>
  )
}
