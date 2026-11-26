'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import { getBankChecks, type BankCheck } from '@/lib/clients'
import { accountName, leftOut, leftOutLabel, money } from '@/lib/ledger'
import { bankBalance, bankCheckNotice, bankCheckText, defaultBank, fullDate, linesCount, linesFor } from '@/lib/sections'
import { sectionHref } from '@/lib/years'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// A tab for each of the client's bank accounts and cards: its check against the statements of the year, then its
// lines. The lines are read-only here: they are edited in Transactions.
export default function BankSection() {
  const { client, year, ledger } = useClientYear()
  const [picked, setPicked] = useState('')
  const [checks, setChecks] = useState<BankCheck[]>([])
  const [notice, setNotice] = useState('')

  // The check is worked out from the year's rows, so it is fetched again whenever they are loaded again.
  useEffect(() => {
    let current = true
    getBankChecks(client.id, year.start)
      .then(found => { if (current) { setChecks(found); setNotice('') } })
      .catch(e => { if (current) { setChecks([]); setNotice(bankCheckNotice(message(e))) } })
    return () => { current = false }
  }, [client.id, year.start, ledger])

  const accounts = client.bank_accounts
  const account = accounts.find(a => a.code === picked) ?? accounts[0]
  if (!account) {
    return (
      <section className="card section">
        <h2>Bank</h2>
        <p className="muted">This client has no bank accounts yet. Add one on the client's details.</p>
      </section>
    )
  }
  const check = checks.find(c => c.code === account.code)
  const lines = linesFor(ledger, account.code)
  const fallback = defaultBank(client)
  const nameOf = (code: string | null | undefined) => accounts.find(a => a.code === (code ?? fallback))?.name ?? 'another account'

  return (
    <>
      {notice && <div className="notice notice-error">{notice}</div>}
      <section className="card section table-card">
        <div className="section-head">
          <h2>Bank</h2>
          <span className="muted small">{linesCount(lines, account.name)}</span>
          <Link href={sectionHref(client.id, year.start, 'transactions')} className="link-btn">Edit in Transactions</Link>
        </div>
        <div className="tabs" role="tablist">
          {accounts.map(a => (
            <button key={a.code} type="button" role="tab" className="tab" aria-selected={a.code === account.code}
                    onClick={() => setPicked(a.code)}>
              {a.name}
            </button>
          ))}
        </div>
        {check && (
          <div className={`notice ${Number(check.difference ?? 0) === 0 && check.statement !== null ? 'notice-info' : 'notice-warn'}`}>
            <span>
              {bankCheckText(check, lines.length)}
              {check.statement !== null && (
                <span className="muted"> In the books {bankBalance(check.books, check.kind)}; on the statement {bankBalance(check.statement, check.kind)}.</span>
              )}
            </span>
          </div>
        )}
        {!!check?.left_out && (
          <div className="notice notice-warn">
            {check.left_out} row{check.left_out === 1 ? '' : 's'} of the year with a problem to fix
            {check.left_out === 1 ? ' is' : ' are'} left out of the books figure. Fix {check.left_out === 1 ? 'it' : 'them'} in Transactions.
          </div>
        )}
        {!lines.length ? <p className="muted">No lines on this account in this year.</p> : (
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th className="num">Money in</th>
                <th className="num">Money out</th>
                <th>Account</th>
              </tr>
            </thead>
            <tbody>
              {lines.map(row => {
                const fromHere = (row.bank_account ?? fallback) === account.code
                // A line on another account's statement that is coded here is the other end of a transfer.
                const incoming = (row.direction === 'in') === fromHere
                // A line a decision left out of the books is listed crossed out, as the Transactions table lists it.
                const left = leftOut(row)
                return (
                  <tr key={row.id} className={left ? 'row-not-booked' : undefined}>
                    <td className="mono">{fullDate(row.date)}</td>
                    <td>
                      <span style={left ? { textDecoration: 'line-through' } : undefined}>{row.description}</span>
                      {left && <div className="row-status">{leftOutLabel(row)}</div>}
                      {!fromHere && <div className="row-origin">Transfer from {nameOf(row.bank_account)}</div>}
                    </td>
                    <td className="num">{incoming ? money(row.gross) : ''}</td>
                    <td className="num">{incoming ? '' : money(row.gross)}</td>
                    <td>{fromHere ? accountName(row) : account.name}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
