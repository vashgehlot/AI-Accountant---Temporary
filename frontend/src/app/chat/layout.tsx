'use client'

import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChatShellContext, type ChatShell } from '@/components/chat/ChatContext'
import ThreadList from '@/components/chat/ThreadList'
import { useConfirm } from '@/components/ConfirmDialog'
import { afterDelete, deleteQuestion, deleteThread, listThreads, newTitle, renameThread, type ChatThread } from '@/lib/chat'
import { listClients, type ClientSummary } from '@/lib/clients'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// The chat: the thread list on the left (behind a button on a phone) and a thread, or New chat, beside it.
export default function ChatLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ threadId?: string }>()
  const router = useRouter()
  const { ask, dialog: confirmDialog } = useConfirm()
  const [clients, setClients] = useState<ClientSummary[] | null>(null)
  const [threads, setThreads] = useState<ChatThread[] | null>(null)
  const [error, setError] = useState('')
  const [listOpen, setListOpen] = useState(false)

  const reloadThreads = useCallback(async () => {
    try {
      setThreads(await listThreads())
    } catch (e) {
      setError(message(e))
    }
  }, [])

  useEffect(() => {
    listClients().then(setClients, (e: unknown) => setError(message(e)))
    reloadThreads()
  }, [reloadThreads])

  // Deleting a chat asks first. The open chat's page moves to New chat, replacing it in the history so Back does
  // not return to a chat that is gone; a chat with a message still running is refused, with the reason shown.
  const deleteChat = useCallback(async (thread: ChatThread) => {
    const clientName = clients?.find(c => c.id === thread.client_id)?.name ?? ''
    if (!(await ask(deleteQuestion(thread, clientName), 'Delete chat'))) return
    setError('')
    try {
      await deleteThread(thread.id)
      const to = afterDelete(thread.id, params.threadId)
      if (to) router.replace(to)
      await reloadThreads()
    } catch (e) {
      setError(message(e))
    }
  }, [ask, clients, params.threadId, reloadThreads, router])

  // Renaming shows the new title at once, in the list and on the open chat, which reads its title from the list.
  const renameChat = useCallback(async (thread: ChatThread, typed: string) => {
    const title = newTitle(typed, thread.title)
    if (!title) return
    setError('')
    try {
      const renamed = await renameThread(thread.id, title)
      setThreads(prev => prev?.map(t => (t.id === renamed.id ? renamed : t)) ?? prev)
      await reloadThreads()
    } catch (e) {
      setError(message(e))
    }
  }, [reloadThreads])

  const shell = useMemo<ChatShell>(() => ({ clients, threads, reloadThreads, deleteChat, renameChat, error }),
                                   [clients, threads, reloadThreads, deleteChat, renameChat, error])
  return (
    <ChatShellContext.Provider value={shell}>
      <div className="chat-space">
        <aside className={listOpen ? 'chat-side open' : 'chat-side'} id="chat-threads">
          <Link href="/chat" className="btn btn-primary chat-new" onClick={() => setListOpen(false)}>New chat</Link>
          <ThreadList threads={threads} clients={clients} activeId={params.threadId} onOpen={() => setListOpen(false)}
                      onDelete={deleteChat} onRename={renameChat} />
        </aside>
        <section className="chat-main">
          <button type="button" className="btn btn-ghost btn-small chat-side-toggle" aria-expanded={listOpen}
                  aria-controls="chat-threads" onClick={() => setListOpen(o => !o)}>
            {listOpen ? 'Hide chats' : 'Chats'}
          </button>
          {error && <div className="notice notice-error">{error}</div>}
          {children}
        </section>
      </div>
      {confirmDialog}
    </ChatShellContext.Provider>
  )
}
