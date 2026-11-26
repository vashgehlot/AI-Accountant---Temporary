'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useRef, useState } from 'react'
import { useChatShell } from '@/components/chat/ChatContext'
import ClientPicker from '@/components/chat/ClientPicker'
import { newThread } from '@/lib/chat'
import type { ClientSummary } from '@/lib/clients'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// New chat: pick the client first. The thread is made on the client's open year, without calling the model.
export default function NewChatPage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <NewChat />
    </Suspense>
  )
}

function NewChat() {
  const router = useRouter()
  const { clients, reloadThreads } = useChatShell()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const params = useSearchParams()
  const linked = useRef(false)                 // a link's client is picked once, even when effects run twice

  // A link's chat replaces the link in the history, so Back from the chat does not make another.
  const pick = async (client: ClientSummary, ask?: string, fromLink = false, yearStart?: string) => {
    setBusy(true)
    setError('')
    try {
      const thread = await newThread(client.id, yearStart)
      await reloadThreads()
      const to = `/chat/${thread.id}${ask ? `?ask=${encodeURIComponent(ask)}` : ''}`
      if (fromLink) router.replace(to)
      else router.push(to)
    } catch (e) {
      setError(message(e))
      setBusy(false)
    }
  }

  // A link (the Overview's) names the client, what to ask and perhaps the year; the chat is made on that client
  // without the picker.
  useEffect(() => {
    const id = params.get('client')
    const client = clients?.find(c => String(c.id) === id)
    if (!client || linked.current) return
    linked.current = true
    pick(client, params.get('ask') ?? undefined, true, params.get('year') ?? undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clients, params])

  if (clients === null) return <p className="muted">Loading clients…</p>
  if (!clients.length) {
    return (
      <div className="empty card">
        <h2>Start a chat to review a client&apos;s books</h2>
        <p className="muted">There are no clients yet.</p>
        <Link href="/" className="btn btn-primary">Add a client</Link>
      </div>
    )
  }
  return (
    <>
      {error && <div className="notice notice-error">{error}</div>}
      <ClientPicker clients={clients} busy={busy} onPick={pick} />
    </>
  )
}
