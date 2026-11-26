'use client'

import { useEffect, useRef, useState } from 'react'
import { answerQuestion, canBookWithout, changedLines, fromQuestion, formatMoney, nextLines, offerDate, offerLines, openingAmount, questionControl, questionState, sourcesFor, splitTotal, uploadForQuestion, type Answer, type AnswerResult, type OfferSource, type Question } from '@/lib/chat'
import type { Answerer } from '@/lib/reviews'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// One question, in amber: what is asked, why it matters, and its answer control. A date or a document goes to the
// question's own route, which returns that question with its effect; a question in words is answered as a chat message.
export default function QuestionCard({ question, number, threadId, answerer, onAnswered, onSay, effect, busy: working }: {
  question: Question
  number: number
  threadId?: string                  // the chat the card is in; the default answerer uses its routes
  answerer?: Answerer                // answers some other way, such as a background review's client routes
  onAnswered: (a: AnswerResult) => void
  onSay: (text: string) => void      // sends a chat message on this thread
  effect: string | null              // what the answer did, shown on every card for this question
  busy: boolean                      // a turn is running: the controls wait, keeping what was typed
}) {
  const [date, setDate] = useState(() => offerDate(question) ?? '')
  const [words, setWords] = useState('')
  const [reason, setReason] = useState<string | null>(null)   // why it is booked without its document, while typed
  // the costs an opening balance goes to: as the agent offered them, if it did, for the person to change or confirm
  const [lines, setLines] = useState(() => offerLines(question) ?? [{ account: '', amount: '' }])
  const [touched, setTouched] = useState(false)   // the person has changed the form: a later offer leaves it alone
  const offeredAt = question.offer?.offered_at
  useEffect(() => {
    setLines(ls => nextLines(ls, question, touched))
    if (!touched && offerDate(question)) setDate(offerDate(question) ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offeredAt])
  const offered = offerLines(question)
  const changed = offered ? changedLines(offered, lines) : []
  const said = (question.offer?.sources ?? []).filter(src => src.kind === 'said')
  const proof = (part: string) => sourcesFor(question, part).filter(src => src.kind === 'document')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const control = questionControl(question)
  const state = questionState(question)

  const run = async (what: string, call: () => Promise<AnswerResult>) => {
    setBusy(what)
    setError('')
    try {
      const result = await call()
      onAnswered(result)
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy('')
    }
  }
  const how: Answerer = answerer ?? {
    answer: (qid, a) => answerQuestion(threadId ?? '', qid, a),
    upload: (qid, file) => uploadForQuestion(threadId ?? '', qid, file),
  }
  const answer = (a: Answer, what: string) => run(what, () => how.answer(question.id, a))
  const upload = (file: File | undefined) => {
    if (file) run(`Reading ${file.name}…`, () => how.upload(question.id, file))
  }
  const needed = openingAmount(question)
  const total = splitTotal(lines)
  const codes = lines.map(l => /^\d{4}/.exec(l.account.trim())?.[0] ?? '')
  const splitReady = needed !== null && total === needed && codes.every(Boolean)
  const setLine = (n: number, change: Partial<{ account: string; amount: string }>) => {
    setTouched(true)
    setLines(ls => ls.map((l, k) => (k === n ? { ...l, ...change } : l)))
  }
  const say = () => {
    if (!words.trim()) return
    onSay(`Answer to "${question.text}": ${words.trim()}`)
    setWords('')
  }

  return (
    <li className={question.status === 'waiting' ? 'question question-waiting' : 'question'}>
      <p className="question-text"><strong>{number}. {question.text}</strong></p>
      <p className="question-why">{question.why}</p>
      {state && <p className="question-state">{state}</p>}
      {question.status !== 'resolved' && <div className="question-controls">
        {control === 'date' && (
          <form className="question-row" onSubmit={e => { e.preventDefault(); if (date) answer({ kind: 'date', date }, 'Saving…') }}>
            <input className="input question-date" type="date" value={date} onChange={e => setDate(e.target.value)}
                   aria-label={question.text} disabled={!!busy || working} />
            <button type="submit" className="btn btn-primary btn-small" disabled={!date || !!busy || working}>Use this date</button>
            <button type="button" className="btn btn-small" disabled={!!busy || working}
                    onClick={() => answer({ kind: 'not_sure' }, 'Saving…')}>Not sure</button>
          </form>
        )}
        {control === 'upload' && (
          <div className="question-row">
            <input ref={fileInput} type="file" hidden onChange={e => { upload(e.target.files?.[0]); e.target.value = '' }} />
            <button type="button" className="btn btn-primary btn-small" disabled={!!busy || working}
                    onClick={() => fileInput.current?.click()}>📎 Upload</button>
            <button type="button" className="btn btn-small" disabled={!!busy || working}
                    onClick={() => answer({ kind: 'no_document' }, 'Saving…')}>I don&apos;t have it</button>
            {canBookWithout(question) && reason === null && (
              <button type="button" className="btn btn-small" disabled={!!busy || working}
                      title="Book it to its account with no VAT reclaimed, saying why there is no document"
                      onClick={() => setReason('')}>Book without it</button>
            )}
          </div>
        )}
        {control === 'upload' && reason !== null && (
          <form className="question-row" onSubmit={e => {
            e.preventDefault()
            if (reason.trim()) answer({ kind: 'without_document', reason: reason.trim() }, 'Booking…')
          }}>
            <input className="input" value={reason} onChange={e => setReason(e.target.value)} maxLength={300} autoFocus
                   aria-label="Why there is no document" placeholder="Why there is no document, e.g. receipt lost"
                   disabled={!!busy || working} />
            <button type="submit" className="btn btn-primary btn-small" disabled={!reason.trim() || !!busy || working}>
              Book with no VAT
            </button>
            <button type="button" className="btn btn-small" onClick={() => setReason(null)}>Cancel</button>
          </form>
        )}
        {control === 'write_off' && (
          <form className="question-row" onSubmit={e => {
            e.preventDefault()
            answer(date ? { kind: 'write_off', date } : { kind: 'write_off' }, 'Writing off…')
          }}>
            <input className="input question-date" type="date" value={date} onChange={e => { setTouched(true); setDate(e.target.value) }}
                   aria-label="Write-off date (blank: when six months overdue)" disabled={!!busy || working} />
            <button type="submit" className="btn btn-primary btn-small" disabled={!!busy || working}>
              {question.offer ? 'Confirm' : 'Write it off'}
            </button>
            <button type="button" className="btn btn-small" disabled={!!busy || working}
                    onClick={() => answer({ kind: 'not_sure' }, 'Saving…')}>Not sure</button>
          </form>
        )}
        {control === 'split' && (
          <form className="question-split" onSubmit={e => {
            e.preventDefault()
            if (splitReady) answer({ kind: 'split', lines: lines.map((l, n) => ({ account: codes[n], amount: l.amount.trim() })) }, 'Releasing…')
          }}>
            {lines.map((l, n) => (
              <div className="question-row" key={n}>
                <input className="input" value={l.account} onChange={e => setLine(n, { account: e.target.value })}
                       aria-label={`Cost account ${n + 1}`} placeholder="Account, e.g. 7100" disabled={!!busy || working} />
                <input className="input" value={l.amount} onChange={e => setLine(n, { amount: e.target.value })}
                       aria-label={`Amount ${n + 1}`} placeholder="Amount" inputMode="decimal" disabled={!!busy || working} />
                {lines.length > 1 && (
                  <button type="button" className="btn btn-small" aria-label={`Remove line ${n + 1}`}
                          onClick={() => { setTouched(true); setLines(ls => ls.filter((_, k) => k !== n)) }}>Remove</button>
                )}
                {changed[n] && <span className="muted small">changed by you</span>}
                {proof(`line:${n + 1}`).map((src, k) => <Proof key={k} source={src} />)}
                {fromQuestion(question, n + 1) && !changed[n] && <span className="muted small">the question&apos;s own amount</span>}
              </div>
            ))}
            <div className="question-row">
              <button type="button" className="btn btn-small" disabled={!!busy || working}
                      onClick={() => { setTouched(true); setLines(ls => [...ls, { account: '', amount: '' }]) }}>Add a cost</button>
              <span className={total === needed ? 'muted' : 'field-error'}>
                {formatMoney(total)} of {needed ? formatMoney(needed) : '—'}
              </span>
              <button type="submit" className="btn btn-primary btn-small" disabled={!splitReady || !!busy || working}>
                {question.offer ? 'Confirm' : 'Release'}
              </button>
            </div>
          </form>
        )}
        {control === 'text' && (
          <form className="question-row" onSubmit={e => { e.preventDefault(); say() }}>
            <input className="input" value={words} onChange={e => setWords(e.target.value)} aria-label={question.text}
                   placeholder="Your answer" disabled={working} />
            <button type="submit" className="btn btn-primary btn-small" disabled={!words.trim() || working}>Send</button>
          </form>
        )}
        {question.offer && (
          <div className="question-offer muted small">
            {said.map((src, k) => <p key={k}>From what you said: “{src.quote}”</p>)}
            {proof('date').map((src, k) => <Proof key={k} source={src} />)}
            <p>{question.offer.reason} Change anything that isn&apos;t right, then Confirm.</p>
          </div>
        )}
        {working && !busy && <span className="muted">You can answer when the current reply finishes.</span>}
        {busy && <span className="progress question-busy"><span className="spinner" /> {busy}</span>}
      </div>}
      {effect && <p className="question-effect">{effect}</p>}
      {error && <p className="field-error">{error}</p>}
    </li>
  )
}

// A document quote an offered figure rests on: which file, its words, and how the figure was worked out.
function Proof({ source }: { source: OfferSource }) {
  return (
    <span className="muted small">
      {source.upload_name || 'Document'}: “{source.quote}”{source.working ? ` (${source.working})` : ''}
    </span>
  )
}
