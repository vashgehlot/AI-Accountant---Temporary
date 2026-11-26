'use client'

import { useEffect, useState } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import { useConfirm } from '@/components/ConfirmDialog'
import JournalDialog from '@/components/JournalDialog'
import OpeningBalancesForm from '@/components/OpeningBalancesForm'
import VatFiguresCard from '@/components/VatFiguresCard'
import type { TrialBalanceResult } from '@/lib/api'
import { closeYear, getSummary, getYearTrialBalance, reopenYear, yearExportUrl } from '@/lib/clients'
import { money } from '@/lib/ledger'
import { balanceText, fullDate, closeQuestion, closeWarnings, statementAmount, statements, trialRows } from '@/lib/sections'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// A client's trial balance for the year: what each account opened with, moved by and closed with. Closing the year
// locks it and carries its balances into the next; the first year also holds the opening balances.
export default function TrialBalancePanel() {
  const { client, year, ledger, reload } = useClientYear()
  const { ask, dialog } = useConfirm()
  const [result, setResult] = useState<TrialBalanceResult | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [journal, setJournal] = useState(false)

  // The figures come from the year's rows, so they are fetched again whenever the year is loaded again.
  useEffect(() => {
    let current = true
    getYearTrialBalance(client.id, year.start)
      .then(found => { if (current) { setResult(found); setError('') } })
      .catch(e => { if (current) { setResult(null); setError(message(e)) } })
    return () => { current = false }
  }, [client.id, year.start, ledger])

  const change = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setNotice('')
    try {
      await action()
      await reload()
    } catch (e) {
      setNotice(message(e))
    } finally {
      setBusy(false)
    }
  }
  const close = async () => {
    // What is unsettled is looked up when asked, so it is as the books stand now; if it can't be, the plain question.
    const summary = await getSummary(client.id, year.start).catch(() => null)
    const warnings = closeWarnings(summary, result, ledger?.transactions.filter(row => !row.excluded && !row.superseded_by) ?? [])
    if (await ask(closeQuestion(year, warnings), warnings.length ? 'Close anyway' : 'Close year')) {
      await change(() => closeYear(client.id, year.start))
    }
  }
  const reopen = () => change(() => reopenYear(client.id, year.start))

  const rows = result ? trialRows(result) : []
  const apart = result ? Math.abs(Number(result.total_debits) - Number(result.total_credits)) : 0
  const netProfit = result?.net_profit ? Number(result.net_profit) : 0
  const firstYear = year.end === client.first_year_end

  return (
    <>
      <section className="card section table-card">
        <div className="section-head">
          <h2>Trial balance</h2>
          <span className="muted small">{year.label}{year.closed && ' · closed'}</span>
          <a className="btn btn-small" href={yearExportUrl(client.id, year.start)} download>Export to Excel</a>
          {!client.archived && !year.closed && (
            <button type="button" className="btn btn-small" onClick={() => setJournal(true)} disabled={busy}>Add journal</button>
          )}
          {!client.archived && (year.closed
            ? <button type="button" className="btn btn-small" onClick={reopen} disabled={busy}>Reopen year</button>
            : <button type="button" className="btn btn-small btn-primary" onClick={close} disabled={busy}>Close year</button>)}
        </div>
        {notice && <div className="notice notice-error">{notice}</div>}
        {error && <div className="notice notice-error">{error}</div>}
        {result && (result.left_out?.length ?? 0) > 0 && (
          <div className="notice notice-warn">
            <span>
              <strong>{result.left_out!.length} row{result.left_out!.length === 1 ? ' is' : 's are'} left out of these
              figures until fixed.</strong> The year can&rsquo;t be closed, and the bank can&rsquo;t be checked, until then.
              {result.left_out!.slice(0, 5).map(p => <span key={p} className="problem">{p}</span>)}
            </span>
          </div>
        )}
        {result && (
          <>
            {/* The figures in the page's own cards and theme colours, so they read in light and dark mode alike. */}
            <div className="figures">
              <div className="card figure">
                <div className="figure-label">{netProfit < 0 ? 'Net loss' : 'Net profit'}</div>
                <div className={`figure-value ${netProfit >= 0 ? 'text-ok' : 'text-error'}`}>
                  {netProfit < 0 ? `(${money(Math.abs(netProfit).toFixed(2))})` : money(result.net_profit ?? '0.00')}
                </div>
              </div>
              <div className="card figure">
                <div className="figure-label">Total income</div>
                <div className="figure-value text-ok">{money(result.total_income ?? '0.00')}</div>
              </div>
              <div className="card figure">
                <div className="figure-label">Total expenses</div>
                <div className="figure-value">{money(result.total_expenses ?? '0.00')}</div>
              </div>
              <div className="card figure">
                <div className="figure-label">Assets / liabilities</div>
                <div className="figure-value">{money(result.total_assets ?? '0.00')} / {money(result.total_liabilities ?? '0.00')}</div>
              </div>
            </div>

            {!rows.length ? <p className="muted">No balances in this year yet.</p> : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Type</th>
                    <th className="num">Opening</th>
                    <th className="num">Movement</th>
                    <th className="num">Closing</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(row => (
                    <tr key={row.code}>
                      <td><span className="mono">{row.code}</span> {row.name}</td>
                      <td><span className="badge badge-muted type-badge">{row.type}</span></td>
                      <td className="num">{balanceText(row.opening)}</td>
                      <td className="num">{balanceText(row.movement)}</td>
                      <td className="num">{balanceText(row.closing)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={4}>Closing debits</td>
                    <td className="num">{money(result.total_debits)}</td>
                  </tr>
                  <tr>
                    <td colSpan={4}>Closing credits</td>
                    <td className="num">{money(result.total_credits)}</td>
                  </tr>
                </tfoot>
              </table>
            )}
            <p className="muted small">Dr is a debit balance and Cr a credit balance. Movement is the year’s own rows.</p>
            <span className={`badge tb-pill ${result.is_balanced ? 'badge-accent' : 'badge-warn'}`}>
              {result.is_balanced ? 'Debits equal credits' : `Out of balance by ${money(apart.toFixed(2))}`}
            </span>
          </>
        )}
      </section>
      {result && rows.length > 0 && (() => {
        const made = statements(rows)
        const table = (title: string, lines: typeof made.profitAndLoss) => (
          <div>
            <h3>{title}</h3>
            <table className="table">
              <tbody>
                {lines.map((l, k) => (
                  <tr key={k} className={l.total ? 'statement-total' : undefined}>
                    <td>{l.label}</td>
                    <td className="num">{statementAmount(l.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
        return (
          <section className="card section table-card">
            <div className="section-head">
              <h2>Profit and loss, and balance sheet</h2>
              <span className="muted small">{year.label} · from the trial balance above</span>
            </div>
            <div className="statements">
              {table('Profit and loss', made.profitAndLoss)}
              {table(`Balance sheet at ${fullDate(year.end)}`, made.balanceSheet)}
            </div>
            {!made.agrees && <div className="notice notice-warn">The balance sheet does not balance: check the trial balance.</div>}
            <p className="muted small">
              Before any year-end journals not yet entered (depreciation, accruals, the tax charge). Amounts in
              brackets are negative.
            </p>
          </section>
        )
      })()}
      {client.vat_registered && <VatFiguresCard />}
      {journal && (
        <JournalDialog client={client} yearStart={year.start} yearEnd={year.end} onCancel={() => setJournal(false)}
                       onSaved={async () => { setJournal(false); await reload() }} />
      )}
      {firstYear && <OpeningBalancesForm client={client} readOnly={year.closed || client.archived} onSaved={reload} />}
      {dialog}
    </>
  )
}
