'use client'

import { useEffect, useState } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import { getVatFigures, type VatFigures } from '@/lib/clients'
import { VAT_BOXES, vatBoxText, vatPeriods } from '@/lib/sections'

// The VAT return boxes for a period of the year, worked from the rows booked in it: a guide to check a return
// against, not the return itself. Only for a client registered for VAT.
export default function VatFiguresCard() {
  const { client, year, ledger } = useClientYear()
  const periods = vatPeriods(year)
  const [picked, setPicked] = useState(0)
  const [figures, setFigures] = useState<VatFigures | null>(null)
  const [error, setError] = useState('')
  const period = periods[picked] ?? periods[0]

  // The figures come from the year's rows, so they are fetched again whenever the year is loaded again.
  useEffect(() => {
    let current = true
    getVatFigures(client.id, year.start, period.start, period.end)
      .then(found => { if (current) { setFigures(found); setError('') } })
      .catch(e => { if (current) { setFigures(null); setError(e instanceof Error ? e.message : String(e)) } })
    return () => { current = false }
  }, [client.id, year.start, period.start, period.end, ledger])

  return (
    <section className="card section table-card">
      <div className="section-head">
        <h2>VAT return figures</h2>
        <label className="year-picker">
          <span>Period</span>
          <select className="input" value={picked} onChange={e => setPicked(Number(e.target.value))} aria-label="VAT period">
            {periods.map((p, i) => <option key={p.start + p.end} value={i}>{p.label}</option>)}
          </select>
        </label>
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      {figures && (
        <>
          <table className="table">
            <tbody>
              {VAT_BOXES.map(([box, label], i) => (
                <tr key={box} className={box === 'box5' ? 'statement-total' : undefined}>
                  <td className="mono">Box {i + 1}</td>
                  <td>{label}</td>
                  <td className="num">{vatBoxText(box, figures[box])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {figures.notes.map(note => <p key={note} className="muted small">{note}</p>)}
        </>
      )}
    </section>
  )
}
