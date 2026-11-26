'use client'

import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import DocumentPanel, { type PanelDocument } from '@/components/DocumentPanel'
import ReviewHistory from '@/components/ReviewHistory'
import TodoList from '@/components/TodoList'
import { useAccountChoices } from '@/components/useAccountChoices'
import { useRowDialogs } from '@/components/useRowDialogs'
import { useTodo } from '@/components/useTodo'
import { clientDecisions, getMateriality } from '@/lib/api'
import { issueFixes, levelsLine, type Levels } from '@/lib/ledger'
import { effectLine, type AnswerResult, type Decision } from '@/lib/chat'
import { changeRow, type RowChange } from '@/lib/clients'
import {
  activityLines, aiChanges, applySuggestion, clientAnswerer, lastReviewed, markReviewsSeen,
  retryReview, reviewNotice, undoDecision,
  type ReviewDetail,
} from '@/lib/reviews'
import { cardDocuments, sameFixGroups } from '@/lib/suggestions'
import { cardKind, checkKinds, doneSince, GROUP_LABELS, needCount, queueGroups, stepAt, waitingSuggestions, type QueueGroup, type TodoCard } from '@/lib/todo'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const RELOAD_EVERY = 3_000     // while a review is running, or one was asked for
const GIVE_UP_AFTER = 120_000  // a review asked for with Try again that never starts

// What needs the person in a client's year, as one list: a card for each row or document with a problem, with the
// change the AI suggests for it and the question it asks about it. One notice says what stands in the way of a
// review (it failed, with Try again; it is paused; it is off). Below, closed until asked for: what the AI changed,
// each with Undo, and one line for each run. Opening the section marks the runs seen.
export default function AiReviewSection() {
  const { client, year, ledger, reload, show } = useClientYear()
  const router = useRouter()
  const todo = useTodo()
  const { runs } = todo
  const [reversed, setReversed] = useState<Set<string>>(new Set()) // the changes some later decision undid
  const [freshRuns, setFreshRuns] = useState<Set<string> | null>(null)   // the runs not looked at when the page opened
  const [made, setMade] = useState<Decision[]>([])   // changes applied from the list on this visit
  const [error, setError] = useState('')
  const [working, setWorking] = useState('')
  const [problems, setProblems] = useState<Record<string, string>>({})   // a refused Undo or Apply, by decision
  const [undone, setUndone] = useState<Set<string>>(new Set())
  const [answers, setAnswers] = useState<{ id: string; text: string; effect: string }[]>([])   // answered on this visit
  // Try again was pressed: the newest run then, and the timer that stops waiting for a new one.
  const [asked, setAsked] = useState<{ newest: string | null } | null>(null)
  const [viewing, setViewing] = useState<string | null>(null)   // the card whose document is open beside the list
  const [levels, setLevels] = useState<Levels | null | undefined>(undefined)   // undefined: not loaded yet
  const { edit, add, dialogs } = useRowDialogs()
  const answerer = clientAnswerer(client.id)
  const readOnly = client.archived || year.closed
  // The accounts a card's row can be coded to, read once for the whole queue.
  const accounts = useAccountChoices(!readOnly && (todo.cards ?? []).some(c =>
    c.kind === 'row' && c.row && c.issues.some(i => issueFixes(c.row!, i).some(f => f.choose === 'account'))))

  const reloadTodo = todo.reload
  // The decisions say which changes a later one undid. The to-do is useTodo's to load: it does so when the page
  // opens and whenever the rows change, so opening the page reads it once.
  const loadDecisions = useCallback(async () => {
    const decisions = await clientDecisions(client.id, year.start)
    setReversed(new Set(decisions.flatMap(d => (d.reverses ? [d.reverses] : []))))
  }, [client.id, year.start])
  const load = useCallback(async () => {
    try {
      const [, loaded] = await Promise.all([loadDecisions(), reloadTodo()])
      setError('')
      return loaded
    } catch (e) {
      setError(message(e))
      return false
    }
  }, [loadDecisions, reloadTodo])
  useEffect(() => {
    loadDecisions().catch(e => setError(message(e)))
    getMateriality(client.id, year.start).then(setLevels, () => setLevels(undefined))
  }, [loadDecisions, client.id, year.start])
  // The runs not looked at when the page opened, kept from the first load; once they are read, they are seen.
  const marked = useRef(false)
  useEffect(() => {
    if (!runs) return
    setFreshRuns(fresh => fresh ?? new Set(runs.filter(r => !r.seen).map(r => r.id)))
    if (!marked.current) {
      marked.current = true
      markReviewsSeen(client.id).catch(() => {})
    }
  }, [runs, client.id])

  // While a review runs, or one was asked for and hasn't started, the runs are read again every few seconds; when
  // it is over the year is read again too, with whatever the review changed, and its run is marked seen.
  const newest = runs?.[0]
  const awaited = !!asked && (newest?.id ?? null) === asked.newest
  const reviewing = awaited || newest?.status === 'running'
  const wasReviewing = useRef(false)
  useEffect(() => {
    if (reviewing) {
      wasReviewing.current = true
      const timer = setInterval(() => { load() }, RELOAD_EVERY)
      return () => clearInterval(timer)
    }
    if (wasReviewing.current) {
      wasReviewing.current = false
      reload()
      markReviewsSeen(client.id).catch(() => {})
    }
  }, [reviewing, load, reload, client.id])
  useEffect(() => {
    if (!asked) return
    const timer = setTimeout(() => setAsked(null), GIVE_UP_AFTER)
    return () => clearTimeout(timer)
  }, [asked])

  const retry = async () => {
    setError('')
    try {
      await retryReview(client.id)
      setAsked({ newest: newest?.id ?? null })
    } catch (e) {
      setError(message(e))
    }
  }

  // The cards, as useTodo works them out for every page.
  const cards = useMemo(() => todo.cards ?? [], [todo.cards])
  const waiting = useMemo(() => waitingSuggestions(cards), [cards])
  const groups = useMemo(() => sameFixGroups(waiting), [waiting])
  // The documents open beside the list: every one its card is about, for as long as the card is on the list.
  const viewed = cards.find(c => c.key === viewing && c.row) ?? null
  const viewedDocuments: PanelDocument[] = viewed
    ? cardDocuments(viewed, ledger.transactions, ledger.uploads).map(({ upload, rowId }) => ({
        upload, rowId, rows: ledger.transactions.filter(r => r.upload_id === upload.id),
        quotes: viewed.suggestions.flatMap(d => d.evidence.filter(e => e.upload_id === upload.id).map(e => e.quote)),
      }))
    : []
  const panelOpen = viewedDocuments.length > 0
  const need = needCount(cards)
  const changes = useMemo(() => aiChanges(runs ?? [], new Set([...reversed, ...undone]), freshRuns ?? new Set()),
                          [runs, reversed, undone, freshRuns])
  const notice = awaited ? { kind: 'reviewing' as const, text: 'Reviewing…', retry: false } : reviewNotice(runs ?? [])
  const reviewed = lastReviewed(runs ?? [])

  // The queue: which group is shown, what kind of thing it is narrowed to, and the kind of warning being worked one by
  // one, at which of its cards. A settled card leaves the list, so the same place then shows the next.
  const [tab, setTab] = useState<'all' | QueueGroup>('all')
  const [kind, setKind] = useState('')
  const [stepping, setStepping] = useState<string | null>(null)
  const [step, setStep] = useState<{ key: string | null; at: number }>({ key: null, at: 0 })   // the card shown, and where
  const first = useRef<number | null>(null)   // how many there were to do when the page opened
  if (first.current === null && todo.need !== null) first.current = todo.need
  const done = doneSince(first.current, need)
  const kinds = [...cards.reduce((m, c) => m.set(cardKind(c), (m.get(cardKind(c)) ?? 0) + 1), new Map<string, number>())]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'en-GB'))
  // A kind or a group whose last card was settled is gone: the queue falls back to every kind, and to All.
  const kindNow = kinds.some(([name]) => name === kind) ? kind : ''
  const kindCards = kindNow ? cards.filter(c => cardKind(c) === kindNow) : cards
  const allGroups = queueGroups(kindCards)
  const tabNow = tab !== 'all' && allGroups.some(g => g.group === tab) ? tab : 'all'
  const stepped = stepping === null ? null
    : { kind: stepping, cards: checkKinds(kindCards).find(k => k.kind === stepping)?.cards ?? [] }
  const at = stepped ? stepAt(stepped.cards, step.key, step.at) : 0
  // The card shown is the one followed: when it is settled, the one that took its place is.
  const shownKey = stepped?.cards[at]?.key ?? null
  useEffect(() => {
    if (shownKey !== null && shownKey !== step.key) setStep({ key: shownKey, at })
  }, [shownKey, at, step.key])
  const stepTo = (n: number) => setStep({ key: stepped?.cards[n]?.key ?? null, at: n })
  const list = (these: TodoCard[]) => (
    <TodoList cards={these} accounts={accounts} working={working} refused={problems} answerer={answerer} viewing={panelOpen ? viewing : null}
              onView={card => setViewing(v => (v === card.key ? null : card.key))} onChange={changeARow}
              onApply={d => change(d, 'apply')} onEdit={edit} onAddLine={add} onAnswered={answered} onSay={say} />
  )

  const change = async (d: Decision, what: 'undo' | 'apply') => {
    setWorking(d.id)
    setProblems(p => ({ ...p, [d.id]: '' }))
    try {
      const done = await (what === 'undo' ? undoDecision : applySuggestion)(client.id, d.id)
      if (what === 'undo') {
        setUndone(u => new Set(u).add(d.id))
        setMade(m => m.filter(x => x.id !== d.id))
      }
      // The checks can refuse a suggestion the books have moved on from: nothing changed, and it says why.
      if (what === 'apply' && done.status === 'refused') setProblems(p => ({ ...p, [d.id]: `Not applied: ${done.reason}` }))
      // A change the person applied belongs to no review run, so it is kept here to be undone.
      if (what === 'apply' && done.status === 'applied') setMade(m => [...m, done])
      await load()
      await reload()
    } catch (e) {
      setProblems(p => ({ ...p, [d.id]: message(e) }))
    } finally {
      setWorking('')
    }
  }

  // These suggestions (all on the list, or those that make the same change), applied one after another; one the
  // checks refuse says why on its card and the rest go on.
  const applyThese = async (these: Decision[], key: string) => {
    setWorking(key)
    for (const d of these) {
      setProblems(p => ({ ...p, [d.id]: '' }))
      try {
        const done = await applySuggestion(client.id, d.id)
        if (done.status === 'refused') setProblems(p => ({ ...p, [d.id]: `Not applied: ${done.reason}` }))
        if (done.status === 'applied') setMade(m => [...m, done])
      } catch (e) {
        setProblems(p => ({ ...p, [d.id]: message(e) }))
      }
    }
    await load()
    await reload()
    setWorking('')
  }

  // A fix made on a card, as on the Transactions page: the year is shown as the API answers, and the suggestions
  // are read again, since a row that has changed can leave one behind.
  const changeARow = async (rowId: number, made: RowChange) => {
    setError('')
    try {
      show(await changeRow(client.id, rowId, made))
      await load()
    } catch (e) {
      setError(message(e))
    }
  }

  const answered = async (a: AnswerResult) => {
    // A question that is settled leaves the list, so what its answer did is said above it. One answered "I don't
    // have it" stays on the list, marked as waiting, and needs no line.
    if (a.question.status === 'resolved') {
      setAnswers(list => [...list.filter(x => x.id !== a.question.id),
                          { id: a.question.id, text: a.question.text, effect: effectLine(a) ?? 'Answered.' }])
    }
    await load()
    await reload()
  }

  const say = (text: string) => router.push(`/chat?client=${client.id}&ask=${encodeURIComponent(text)}`)

  return (
    <section className="card section">
      <div className="section-head"><h2>AI review</h2></div>
      {(error || todo.error) && <div className="notice notice-error">{error || todo.error}</div>}
      {notice && (
        <div className={notice.kind === 'failed' ? 'notice notice-warn' : 'notice notice-info'}>
          <span>{notice.kind === 'reviewing' && <span className="spinner" aria-hidden="true" />} {notice.text}</span>
          {notice.retry && (
            <button type="button" className="btn btn-small" disabled={readOnly} onClick={retry}>Try again</button>
          )}
        </div>
      )}
      {answers.map(a => <p key={a.id} className="muted small todo-done">{a.text} {a.effect}</p>)}
      {!runs && !error && !todo.error && <p className="muted">Loading the reviews…</p>}
      {runs && (
        <>
          <div className="todo-top">
            {cards.length > 0 ? (
              <div className="queue-head">
                <h3>{need > 0 ? `${need} to do` : 'Nothing to do now'}</h3>
                {cards.length > need && <span className="muted small">{cards.length - need} waiting on you</span>}
                {done > 0 && <span className="muted small">{done} done since you opened this page</span>}
              </div>
            ) : (
              <p className="muted">
                Nothing needs you.{' '}
                {reviewed ? `Last reviewed ${reviewed}.`
                  : runs.length === 0 ? 'No review has run on this year yet. One runs after the books change and go quiet.' : ''}
              </p>
            )}
            {waiting.length > 1 && (
              <button type="button" className="btn btn-small btn-primary" disabled={!!working || readOnly} onClick={() => applyThese(waiting, 'all')}>
                {working === 'all' ? 'Applying…' : `Apply all ${waiting.length} suggestions`}
              </button>
            )}
          </div>
          {cards.length > 0 && (
            <div className="queue-progress" role="progressbar" aria-label="Done since you opened this page"
                 aria-valuemin={0} aria-valuemax={done + need} aria-valuenow={done}>
              <div style={{ width: `${done + need ? (100 * done) / (done + need) : 0}%` }} />
            </div>
          )}
          {levels !== undefined && <p className="hint">{levelsLine(levels)}</p>}
          {/* The same change suggested for several rows, applied together and apart from the rest. */}
          {groups.map(group => (
            <div key={group.key} className="question-row todo-group">
              <span className="small">{group.label}</span>
              <button type="button" className="btn btn-small" disabled={!!working || readOnly}
                      onClick={() => applyThese(group.suggestions, group.key)}>
                {working === group.key ? 'Applying…' : `Apply to all ${group.suggestions.length}`}
              </button>
            </div>
          ))}
          {cards.length > 0 && (
            <div className="queue-tabs" role="group" aria-label="Show">
              <button type="button" className="queue-tab" aria-pressed={tabNow === 'all'} onClick={() => setTab('all')}>
                All <span>{needCount(kindCards)}</span>
              </button>
              {allGroups.map(g => (
                <button key={g.group} type="button" className={`queue-tab queue-tab-${g.group}`} aria-pressed={tabNow === g.group}
                        onClick={() => setTab(g.group)}>
                  {GROUP_LABELS[g.group].title} <span>{g.cards.length}</span>
                </button>
              ))}
              <select className="input queue-kind" aria-label="Kind" value={kindNow}
                      onChange={e => { setKind(e.target.value); setStepping(null) }}>
                <option value="">Any kind</option>
                {kinds.map(([name, n]) => <option key={name} value={name}>{name} · {n}</option>)}
              </select>
            </div>
          )}
          <div className={panelOpen ? 'todo-with-panel todo-panel-open' : 'todo-with-panel'}>
            <div className="queue">
              {allGroups.filter(g => tabNow === 'all' || tabNow === g.group).map(g => (
                <div key={g.group} className="queue-group">
                  <h4 className="queue-group-head">
                    {GROUP_LABELS[g.group].title} <span className="muted">· {g.cards.length}</span>
                    <span className="muted small"> {GROUP_LABELS[g.group].note}</span>
                  </h4>
                  {g.group !== 'check' ? list(g.cards) : stepped ? (
                    <div className="queue-step">
                      <div className="queue-step-bar">
                        <button type="button" className="btn btn-small" onClick={() => setStepping(null)}>All kinds</button>
                        <strong>{stepped.kind}</strong>
                        {stepped.cards.length > 0 ? (
                          <>
                            <span className="muted small">{at + 1} of {stepped.cards.length}</span>
                            <button type="button" className="btn btn-small" disabled={at === 0} onClick={() => stepTo(at - 1)}>Previous</button>
                            <button type="button" className="btn btn-small" disabled={at >= stepped.cards.length - 1}
                                    onClick={() => stepTo(at + 1)}>Next</button>
                          </>
                        ) : <span className="muted small">All checked</span>}
                      </div>
                      {stepped.cards[at] && list([stepped.cards[at]])}
                    </div>
                  ) : (
                    <ul className="queue-kinds">
                      {checkKinds(g.cards).map(k => (
                        <li key={k.kind}>
                          <button type="button" className="queue-kind-line" onClick={() => { setStepping(k.kind); setStep({ key: k.cards[0]?.key ?? null, at: 0 }) }}>
                            <span>{k.kind}</span>
                            <span className="muted small">{k.cards.length} {k.cards.every(c => c.kind === 'document') ? (k.cards.length === 1 ? 'document' : 'documents') : k.cards.length === 1 ? 'row' : 'rows'} · one by one ›</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
            {panelOpen && <DocumentPanel documents={viewedDocuments} onClose={() => setViewing(null)} />}
          </div>
          <ReviewHistory changes={changes} made={made} lines={activityLines(runs)} readOnly={readOnly} working={working}
                         refused={problems} onUndo={d => change(d, 'undo')} />
        </>
      )}
      {dialogs}
    </section>
  )
}
