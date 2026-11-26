'use client'

import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useChatShell } from '@/components/chat/ChatContext'
import Composer from '@/components/chat/Composer'
import ReplyResult from '@/components/chat/ReplyResult'
import RunSteps from '@/components/chat/RunSteps'
import TitleEditor from '@/components/chat/TitleEditor'
import { ApiError } from '@/lib/api'
import {
  ATTENTION, POLL_MS, currentTitle, effectLine, fileStatus, getThread, hasResult, readStatus, retryFiles, shouldPoll, stopRun, streamMessage, withQuestion,
  type AnswerResult, type ChatError, type ChatEvent, type ChatMessage, type Step, type ThreadDetail, type TurnResult,
 plainReply } from '@/lib/chat'
import { getYears } from '@/lib/clients'
import { sectionHref } from '@/lib/years'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

const SUGGESTIONS = ["Review the documents I'm adding", ATTENTION, 'Show the trial balance']

// One message sent from this page and what came back for it.
interface Turn {
  id: number
  text: string
  files: File[]
  bankAccounts: string[]
  steps: Step[]
  status: string
  reply: string
  result: TurnResult | null
  error: ChatError | null
  running: boolean
}

// A chat about one client's year: the messages so far, the turn running now with its steps and streamed text, each
// reply with the cards its own turn raised, and the message box. Answering a card updates it in place.
export default function ThreadPage() {
  const { threadId } = useParams<{ threadId: string }>()
  const { clients, threads, reloadThreads, deleteChat, renameChat } = useChatShell()
  const ask = useSearchParams().get('ask')
  const [detail, setDetail] = useState<ThreadDetail | null>(null)
  const [history, setHistory] = useState<ChatMessage[]>([])
  const [turns, setTurns] = useState<Turn[]>([])
  const [yearLabel, setYearLabel] = useState('')
  const [draft, setDraft] = useState('')
  const [missing, setMissing] = useState(false)
  const [renaming, setRenaming] = useState(false)   // the chat's title is a box to type in
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const running = turns.some(t => t.running)
  const ownRunning = useRef(false)               // read by a load, which may outlive the render that made it
  ownRunning.current = running
  const [effects, setEffects] = useState<Record<string, string>>({})   // each answered question's effect, on every card for it
  const abort = useRef<AbortController | null>(null)
  const nextTurn = useRef(1)
  const loads = useRef(0)                        // a load that a newer one or an unmount has replaced must not apply
  const asked = useRef(false)                    // the link's question is handled once, even when effects run twice
  const poll = useRef<ReturnType<typeof setTimeout> | null>(null)   // the next load while a turn this page did not send runs
  const end = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    const mine = ++loads.current
    if (poll.current) clearTimeout(poll.current)
    try {
      const next = await getThread(threadId)
      if (mine !== loads.current) return
      setDetail(next)
      setHistory(next.messages)
      setTurns([])
      setMissing(false)
      setError('')
      if (shouldPoll(next, ownRunning.current)) poll.current = setTimeout(() => { load() }, POLL_MS)
      getYears(next.thread.client_id).then(years => setYearLabel(years.find(y => y.start === next.thread.year_start)?.label ?? ''),
                              () => undefined)
    } catch (e) {
      if (mine !== loads.current) return
      if (e instanceof ApiError && e.code === 'http_404') setMissing(true)
      else setError(message(e))
    }
  }, [threadId])

  useEffect(() => {
    load()
    return () => { loads.current++; if (poll.current) clearTimeout(poll.current); abort.current?.abort() }
  }, [load])

  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [turns.length])

  const change = (id: number, patch: (t: Turn) => Partial<Turn>) =>
    setTurns(prev => prev.map(t => (t.id === id ? { ...t, ...patch(t) } : t)))

  const send = async (text: string, files: File[], bankAccounts: string[]) => {
    if (running || detail?.running) return
    const id = nextTurn.current++
    setTurns(prev => [...prev, { id, text, files, bankAccounts, steps: [], status: 'Working on it…', reply: '', result: null, error: null, running: true }])
    setNotice('')
    const controller = new AbortController()
    abort.current = controller
    let finished = false
    const onEvent = (event: ChatEvent) => {
      switch (event.type) {
        case 'status': change(id, () => ({ status: event.data.text })); break
        case 'step': change(id, t => ({
          steps: t.steps.some(s => s.id === event.data.id)
            ? t.steps.map(s => (s.id === event.data.id ? event.data : s))
            : [...t.steps, event.data],
        })); break
        case 'token': change(id, t => ({ reply: t.reply + event.data.text })); break
        case 'result': change(id, () => ({ result: event.data })); break
        case 'error': finished = true; change(id, () => ({ error: event.data })); break
        case 'done': finished = true; break
      }
    }
    try {
      await streamMessage(threadId, text, files, bankAccounts, onEvent, controller.signal)
      change(id, () => ({ running: false }))
      if (!finished) await lostConnection()
    } catch (e) {
      if (controller.signal.aborted) return
      if (e instanceof ApiError && e.code.startsWith('http_')) {
        change(id, () => ({ running: false, error: { code: e.code, message: e.message } }))
      } else {
        await lostConnection()
      }
    } finally {
      reloadThreads()
    }
  }

  // A link (the Overview's) may carry a question to ask in a new chat. Only a suggested prompt is ever sent, and only
  // into an empty chat; any other (Ask the AI on a row's issue) is put in the message box for the person to read and
  // send, so no link can make the chat say something by itself. The address then loses it, so a reload does not ask
  // again. The address is changed with the history
  // API, not router.replace: a Next navigation remounts the page, which would abort the turn just started.
  useEffect(() => {
    if (ask === null || !detail || asked.current) return
    asked.current = true
    if (SUGGESTIONS.includes(ask) && !history.length && !turns.length) send(ask, [], [])
    else if (!history.length && !turns.length) setDraft(ask.slice(0, 2000))
    window.history.replaceState(null, '', `/chat/${threadId}`)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ask, detail])

  // The stream broke off before the turn ended: what the server has is the truth, so the thread is loaded again.
  const lostConnection = async () => {
    await load()
    setNotice('The connection was lost, so the chat was loaded again.')
  }

  const stop = () => {
    const live = turns.find(t => t.running)
    if (live) change(live.id, () => ({ status: 'Stopping…' }))
    stopRun(threadId).catch((e: unknown) => setNotice(message(e)))
  }

  const retry = (turn: Turn) => {
    const again = retryFiles(turn.files, turn.bankAccounts, turn.steps)
    send(turn.text, again.files, again.bankAccounts)
  }

  if (missing) {
    return (
      <div className="empty card">
        <h2>Chat not found</h2>
        <p className="muted">It may have been deleted, or the link is wrong.</p>
        <Link href="/chat" className="btn">New chat</Link>
      </div>
    )
  }
  if (error) return <div className="notice notice-error">{error}</div>
  if (!detail) return <p className="muted">Loading…</p>

  const thread = detail.thread
  const client = clients?.find(c => c.id === thread.client_id)
  const waiting = detail.running && !running     // a turn works on the chat that this page did not send
  const busy = running || waiting
  const fresh = !history.length && !turns.length
  const title = currentTitle(thread, threads)
  const last = turns[turns.length - 1]
  const onAnswered = (a: AnswerResult) => {
    const line = effectLine(a)
    setEffects(e => ({ ...e, [a.question.id]: line ?? '' }))
    setHistory(h => withQuestion(h, a.question))
    setTurns(ts => withQuestion(ts, a.question))
  }
  return (
    <div className="chat-thread">
      <div className="chat-head">
        <div className="chat-head-text">
          <h1>
            {client
              ? <Link href={sectionHref(client.id, thread.year_start, 'overview')} className="strong">{client.name}</Link>
              : 'Loading…'}
          </h1>
          {renaming ? (
            <p className="muted chat-head-rename">
              {yearLabel && <span>{yearLabel} ·</span>}
              <TitleEditor title={title} onCancel={() => setRenaming(false)}
                           onSave={typed => { setRenaming(false); renameChat({ ...thread, title }, typed) }} />
            </p>
          ) : <p className="muted">{[yearLabel, title].filter(Boolean).join(' · ')}</p>}
        </div>
        <div className="chat-head-actions">
          <button type="button" className="btn btn-ghost btn-small" onClick={() => setRenaming(true)}>Rename</button>
          <button type="button" className="btn btn-ghost btn-small" disabled={busy}
                  title={busy ? 'A message is still being worked on' : undefined}
                  onClick={() => deleteChat({ ...thread, title })}>Delete chat</button>
        </div>
      </div>

      <div className="transcript">
        {history.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'bubble-user' : 'bubble-agent'}>
            {m.role === 'user' ? m.text : plainReply(m.text)}
            {m.files.length > 0 && (
              <ul className="file-chips sent">
                {m.files.map((f, j) => {
                  const status = readStatus(f)
                  return (
                    <li key={j} className={`file-chip file-${status.state}`} title={status.label}>
                      <span className="file-chip-name">{f.name}</span>
                      <span className="file-chip-status">{status.label}</span>
                    </li>
                  )
                })}
              </ul>
            )}
            {hasResult(m.result) && (
              <ReplyResult result={m.result} threadId={threadId} onAnswered={onAnswered} onSay={text => send(text, [], [])}
                             effects={effects} busy={busy} />
            )}
          </div>
        ))}
        {turns.map(t => (
          <div key={t.id} className="turn">
            <div className="bubble-user">
              {t.text}
              {t.files.length > 0 && (
                <ul className="file-chips sent">
                  {t.files.map((f, i) => {
                    const status = fileStatus(f.name, t.steps)
                    return (
                      <li key={i} className={`file-chip file-${status.state}`} title={status.label}>
                        <span className="file-chip-name">{f.name}</span>
                        <span className="file-chip-status">{status.state === 'reading' && <span className="spinner" />} {status.label}</span>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
            <div className="bubble-agent">
              <RunSteps steps={t.steps} status={t.status} running={t.running} />
              {t.reply && <p className="narrative">{plainReply(t.reply)}</p>}
              {hasResult(t.result) && (
                <ReplyResult result={t.result} threadId={threadId} onAnswered={onAnswered} onSay={text => send(text, [], [])}
                             effects={effects} busy={busy} />
              )}
              {t.error && t === last && <RunError error={t.error} onRetry={() => retry(t)} onContinue={() => send('Continue', [], [])} />}
            </div>
          </div>
        ))}
        {waiting && (
          <div className="bubble-agent">
            <RunSteps steps={[]} status="Still working on your message…" running />
          </div>
        )}
        {notice && <div className="notice notice-info">{notice}</div>}

        <div ref={end} />
      </div>

      {fresh && (
        <div className="suggestions">
          {SUGGESTIONS.map(s => (
            <button key={s} type="button" className="chip" onClick={() => setDraft(s)}>{s}</button>
          ))}
        </div>
      )}
      <Composer text={draft} onText={setDraft} bankAccounts={client?.bank_accounts ?? []} running={busy}
                onSend={send} onStop={stop} />
    </div>
  )
}

// Why a turn ended early, with the way on: Retry (the model was unavailable or something failed), New chat, or
// Continue (the turn ran out of steps).
function RunError({ error, onRetry, onContinue }: { error: ChatError; onRetry: () => void; onContinue: () => void }) {
  if (error.code === 'loop_limit') {
    return (
      <div className="notice notice-warn">
        <span>Stopped after {error.steps ?? 'too many'} steps.</span>
        <button type="button" className="btn btn-small" onClick={onContinue}>Continue</button>
      </div>
    )
  }
  return (
    <div className="notice notice-error run-error">
      <span>{error.code === 'model_unavailable' ? `The model isn't available: ${error.message}` : error.message}</span>
      <span className="run-error-actions">
        <button type="button" className="btn btn-small" onClick={onRetry}>Retry</button>
        <Link href="/chat" className="btn btn-small btn-ghost">New chat</Link>
      </span>
    </div>
  )
}
