'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { clientDecisions, postedTrialBalance, type Issue } from '@/lib/api'
import { agentDecisions, type Decision } from '@/lib/chat'
import { useClientYear } from '@/components/ClientYearContext'
import FilterBar from '@/components/FilterBar'
import { MARKS } from '@/components/IssueList'
import RowPanel from '@/components/RowPanel'
import { useAccountChoices } from '@/components/useAccountChoices'
import { type Ledger, type RowChange, type SavedRow } from '@/lib/clients'
import { DOCUMENT_TYPES, transactionCount } from '@/lib/clientRules'
import { filtersSet, issueFixes, keepSelected, matchesFilters, NO_FILTERS, pageOf, pageReaching, ROWS_PER_PAGE, rowHeadline, signedAmount, tableDate, type RowFilters } from '@/lib/ledger'
import { accountName, checkHover, documentProblems, kindOf, leftOut, money, needsReview, reviewSummary, rowIssues, totalsOf } from '@/lib/ledger'


// The worst issue on a row, as the Check column shows it. A row left out of the books needs no review, whatever its
// issues say: they stay listed under its description, unmarked.
function checkOf(issues: Issue[], left: boolean) {
  if (left) return { mark: '—', cls: 'check-info', title: 'Left out of the books: nothing to review' }
  if (!issues.length) return { mark: '✓', cls: 'check-ok', title: 'No issues' }
  const worst = issues.some(i => i.severity === 'error') ? 'error' : issues.some(i => i.severity === 'warning') ? 'warning' : 'info'
  const cls = { error: 'check-error', warning: 'check-warn', info: 'check-info' }[worst]
  return { mark: `${MARKS[worst]} ${issues.length}`, cls, title: checkHover(issues) }
}

// The client's saved rows: what needs review and why, statuses with Link, Unlink and Include, Edit, Add line,
// Remove and Revert, and totals. When readOnly (a closed year or an archived client) no control changes a row; Show
// both and the filters still work.
export default function TransactionsTable({ ledger, readOnly, onChange, onEdit, onAdd, onRemove, show, saving }: {
  ledger: Ledger
  show?: number[]                               // rows to open on, side by side (a link from the problems list)
  saving?: Set<number>                          // rows whose change is being saved: dimmed until it is
  readOnly: boolean
  onChange: (rowId: number, change: RowChange) => void
  onEdit?: (row: SavedRow) => void
  onAdd?: (lineOf: SavedRow | null) => void     // a new transaction, or a line of the row's document
  onRemove?: (row: SavedRow) => void
}) {
  const { client, year } = useClientYear()
  const rows = ledger.transactions
  const [decisions, setDecisions] = useState<Map<string, Decision>>(new Map())
  const [held, setHeld] = useState<Set<number>>(new Set())   // rows waiting in Suspense for a document
  // The accounts a row can be coded to, read only when a row has an issue that is fixed by choosing one.
  const accounts = useAccountChoices(!readOnly && rows.some(r => r.issues.some(i => issueFixes(r, i).some(f => f.choose === 'account'))))
  // The row open in the panel beside the table, or none.
  const [selected, setSelected] = useState<number | null>(show?.length ? show[0] : null)
  // The decisions and the posted ledger's held rows are read again whenever the rows are loaded again; a failure
  // leaves the table as it was.
  useEffect(() => {
    let current = true
    clientDecisions(client.id, year.start)
      .then(found => { if (current) setDecisions(new Map(found.map(d => [d.id, d]))) }).catch(() => {})
    postedTrialBalance(client.id, year.start)
      .then(tb => { if (current) setHeld(new Set(tb.suspense.filter(s => s.needs).map(s => s.row_id))) }).catch(() => {})
    return () => { current = false }
  }, [client.id, year.start, ledger])
  // Why a row was left out: the reason of the decision that did it (the latest of those that touched the row).
  const whyLeftOut = (row: SavedRow): string | null => {
    const ids = row.superseded_by ? [row.superseded_by] : [...(row.decision_ids ?? [])].reverse()
    for (const id of ids) { const d = decisions.get(id); if (d?.reason) return d.reason }
    return null
  }
  const [only, setOnly] = useState<string | null>(null)   // an issue code, 'review' for every flagged row, or all
  const [focus, setFocus] = useState<number[] | null>(show?.length ? show : null)   // rows shown side by side (Show both), or none
  const [byDate, setByDate] = useState(true)
  const card = useRef<HTMLElement>(null)
  const uploads = useMemo(() => new Map(ledger.uploads.map(u => [u.id, u.name])), [ledger.uploads])
  const byId = useMemo(() => new Map(rows.map(r => [r.id, r])), [rows])
  // Each row's own issues, a possible duplicate among them (worked out with the books, so the AI sees it too). A
  // problem with a whole document is not its first line's: it heads each of its lines, and their panels list it.
  const issuesOf = useMemo(() => rows.map(rowIssues), [rows])
  const docs = useMemo(() => documentProblems(rows), [rows])
  // Rows left out of the books are listed, crossed out, but are never counted or filtered as rows to review.
  const review = useMemo(() => reviewSummary([...issuesOf.filter((_, i) => !leftOut(rows[i])), ...docs.map(d => [d.issue])]),
                         [rows, issuesOf, docs])
  const flaggedRows = rows.filter((row, i) => needsReview(row, issuesOf[i])).length
  const all = rows.map((row, i) => ({ row, issues: issuesOf[i] }))
  // The filters narrow the table by several fields at once; the review chips then pick among the rows left.
  const [filters, setFilters] = useState<RowFilters>(NO_FILTERS)
  const narrowed = filtersSet(filters) > 0
  const passing = narrowed ? all.filter(({ row }) => matchesFilters(row, filters, uploads.get(row.upload_id))) : all
  const accountChoices = useMemo(() => [...new Map(rows.filter(r => r.account_code).map(r =>
    [r.account_code, r.account_name || r.account_code])).entries()].sort((a, b) => a[1].localeCompare(b[1], 'en-GB')), [rows])
  const typeChoices = useMemo(() => [...new Set(rows.map(r => r.document_type ?? 'receipt'))], [rows])
  // A chip also shows every line of a document with that problem ("Only these": with any problem).
  const ofDocs = new Set(docs.filter(d => only === 'review' || d.issue.code === only).flatMap(d => d.lines))
  const shown = passing.filter(({ row, issues }) => only === null || ofDocs.has(row.id)
    || (only === 'review' ? needsReview(row, issues) : !leftOut(row) && issues.some(i => i.code === only)))
  const filter = only !== null && !shown.length ? null : only   // a filter whose rows are all fixed shows everything
  const together = focus ? all.filter(({ row }) => focus.includes(row.id)) : []
  const picked = together.length ? together : filter === null ? passing : shown
  // The totals are of the whole year, or, while the table is narrowed, of the rows it shows.
  const totals = totalsOf(narrowed && !together.length ? picked.map(p => p.row) : rows)
  // By date, oldest first, undated rows first so they are seen; or as the files were read, each document's rows
  // together. Rows of one day keep the order they were read in.
  const listed = byDate
    ? picked.map((item, n) => ({ item, n })).sort((a, b) =>
        (a.item.row.date ?? '').localeCompare(b.item.row.date ?? '') || a.n - b.n).map(({ item }) => item)
    : picked
  // A page at a time, back to the first whenever what is listed changes.
  const [limit, setLimit] = useState(ROWS_PER_PAGE)
  useEffect(() => { setLimit(ROWS_PER_PAGE) }, [filters, only, focus, byDate])
  // ...but always far enough to show the row open in the panel (after Show all, it can be the 900th).
  const listedIds = listed.map(p => p.row.id).join(',')
  useEffect(() => {
    setLimit(l => pageReaching(listedIds ? listedIds.split(',').map(Number) : [], selected, l))
  }, [selected, listedIds])
  const page = pageOf(listed, limit)
  // Rows shown side by side keep the row open in the panel when it is one of them (Show its lines).
  const showTogether = (ids: number[]) => {
    setFocus(ids)
    setSelected(s => keepSelected(s, ids))
    card.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }
  // Back to every row, at the one open in the panel.
  const scrollTo = useRef<number | null>(null)
  const showAll = () => {
    setFocus(null)
    scrollTo.current = selected
  }
  useEffect(() => {
    if (scrollTo.current === null) return
    const found = document.getElementById(`row-${scrollTo.current}`)
    if (found) {
      found.scrollIntoView({ block: 'center' })
      scrollTo.current = null
    }
  })
  // A document's problems, by each of its lines.
  const docsOf = useMemo(() => {
    const found = new Map<number, typeof docs>()
    for (const d of docs) for (const id of d.lines) found.set(id, [...(found.get(id) ?? []), d])
    return found
  }, [docs])
  const open = selected === null ? null : byId.get(selected) ?? null
  // Esc closes the panel; up and down open the row above or below, unless a field is being typed in.
  const ids = page.shown.map(p => p.row.id)
  useEffect(() => {
    if (selected === null) return
    const onKey = (e: KeyboardEvent) => {
      const at = document.activeElement
      if (at instanceof HTMLInputElement || at instanceof HTMLSelectElement || at instanceof HTMLTextAreaElement) return
      // Not while a dialog is open over the page (Edit, Remove), nor for a key held with another.
      if (e.defaultPrevented || e.altKey || e.metaKey || e.ctrlKey || e.shiftKey || (at as HTMLElement | null)?.isContentEditable
          || document.querySelector('[aria-modal="true"]')) return
      if (e.key === 'Escape') { setSelected(null); return }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
      const next = ids[ids.indexOf(selected) + (e.key === 'ArrowDown' ? 1 : -1)]
      if (next === undefined) return
      e.preventDefault()
      setSelected(next)
      document.getElementById(`row-${next}`)?.scrollIntoView({ block: 'nearest' })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, ids.join(',')])   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section ref={card} className="card section">
      <div className="section-head">
        <h2>Transactions</h2>
        <span className="muted small">{transactionCount(rows.length)}</span>
        <button type="button" className="btn btn-small" onClick={() => setByDate(v => !v)}
                title={byDate ? 'Listed by date, oldest first' : 'Listed as the files were read'}>
          {byDate ? 'Order: by date' : 'Order: as read'}
        </button>
        {!readOnly && onAdd && (
          <button type="button" className="btn btn-small" onClick={() => onAdd(null)}>Add transaction</button>
        )}
      </div>
      {rows.length > 0 && !together.length && (
        <FilterBar filters={filters} onFilters={setFilters} review={review} only={filter} onOnly={setOnly}
                   flaggedRows={flaggedRows} flaggedDocuments={docs.length}
                   accounts={accountChoices} types={typeChoices} shown={listed.length} total={rows.length} />
      )}
      {together.length > 0 ? (
        <div className="review-bar" role="group" aria-label="Rows shown together">
          <span className="review-count">{transactionCount(together.length)} side by side</span>
          <button type="button" className="chip chip-on" onClick={showAll}>Show all</button>
        </div>
      ) : null}
      {!rows.length ? <p className="muted">Add documents to see their transactions here.</p> : (
        <div className={open ? 'ledger-with-panel ledger-panel-open' : 'ledger-with-panel'}>
        <table className="table ledger-table">
          <thead>
            <tr>
              <th className="col-date">Date</th>
              <th>Description</th>
              <th className="num col-amount">Amount</th>
              <th className="col-account">Account</th>
              <th className="col-check" aria-label="Check" />
            </tr>
          </thead>
          <tbody>
            {page.shown.map(({ row, issues }) => {
              const left = leftOut(row)
              const ofDocument = docsOf.get(row.id)?.[0]?.issue ?? null
              const check = checkOf(ofDocument ? [...issues, ofDocument] : issues, left)
              const head = rowHeadline(row, issues, ofDocument, left ? whyLeftOut(row) : null)
              const amount = signedAmount(row)
              const worst = check.cls === 'check-error' || head.severity === 'error' ? 'row-flag-error'
                : check.cls === 'check-warn' || head.severity === 'warning' ? 'row-flag-warn' : ''
              const classes = [left || kindOf(row) === 'not booked' ? 'row-not-booked' : '', left ? '' : worst,
                               selected === row.id ? 'row-selected' : '']
              return (
                <tr key={row.id} id={`row-${row.id}`} className={classes.filter(Boolean).join(' ') || undefined}
                    aria-selected={selected === row.id} tabIndex={0} aria-label={`${row.description}: open`}
                    onClick={() => setSelected(id => (id === row.id ? null : row.id))}
                    onKeyDown={e => {
                      if (e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return
                      e.preventDefault()
                      setSelected(id => (id === row.id ? null : row.id))
                    }}
                    aria-busy={saving?.has(row.id) || undefined} style={saving?.has(row.id) ? { opacity: 0.5 } : undefined}>
                  <td className="mono col-date">{tableDate(row.date)}</td>
                  <td className="col-description">
                    <div className="row-line" title={row.description} style={left ? { textDecoration: 'line-through' } : undefined}>
                      {row.description}
                      {row.edited && <span className="badge badge-muted edited">Edited</span>}
                      {row.decision_ids?.length ? <span className="badge badge-accent">Agent</span> : null}
                      {held.has(row.id) && <span className="badge badge-warn">Documentation required</span>}
                    </div>
                    <div className={`row-sub${head.severity ? ` row-sub-${head.severity}` : ''}`}
                         title={`${uploads.get(row.upload_id) ?? ''} · ${DOCUMENT_TYPES[row.document_type ?? 'receipt'] ?? row.document_type}`}>
                      {head.text}
                    </div>
                  </td>
                  <td className={`num mono amount-${amount.tone}`}>{amount.text}</td>
                  <td className="col-account"><div className="row-line" title={accountName(row)}>{accountName(row)}</div></td>
                  <td className={`check ${check.cls}`} title={check.title}>{check.mark}</td>
                </tr>
              )
            })}
            {page.more > 0 && (
              <tr><td colSpan={5}>
                <button type="button" className="btn btn-small" onClick={() => setLimit(l => l + ROWS_PER_PAGE)}>
                  Show {Math.min(ROWS_PER_PAGE, page.more)} more
                </button>{' '}
                <span className="muted small">{page.more} not shown yet</span>
              </td></tr>
            )}
          </tbody>
          <tfoot>
            {narrowed && !together.length && (
              <tr><td colSpan={5} className="muted small">
                {listed.length ? `Totals of the ${transactionCount(listed.length)} shown` : 'No transactions match these filters.'}
              </td></tr>
            )}
            {totals.map(t => (
              <tr key={t.key}>
                <td colSpan={2}>
                  {t.label} ({transactionCount(t.count)})
                  <div className="muted small" title={t.vat == null || t.net == null ? 'Fix the rows marked ✖ first' : undefined}>
                    VAT {money(t.vat)} · net {money(t.net)}{t.stillOwed != null && ` · ${money(t.stillOwed)} still owed`}
                  </div>
                </td>
                <td className="num mono">{money(t.gross)}</td>
                <td colSpan={2} />
              </tr>
            ))}
          </tfoot>
        </table>
        {open && (
          <RowPanel key={open.id} row={open} issues={issuesOf[rows.indexOf(open)] ?? []} documentProblems={docsOf.get(open.id) ?? []}
                    rows={rows} uploads={ledger.uploads}
                    decisions={open.decision_ids?.length ? agentDecisions(open.decision_ids, decisions) : []}
                    held={held.has(open.id)} whyLeftOut={whyLeftOut(open)} readOnly={readOnly} accounts={accounts}
                    onChange={onChange} onEdit={onEdit} onAdd={onAdd} onRemove={onRemove}
                    onShowTogether={showTogether} onClose={() => setSelected(null)} />
        )}
        </div>
      )}
    </section>
  )
}
