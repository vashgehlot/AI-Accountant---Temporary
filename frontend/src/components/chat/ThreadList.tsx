'use client'

import Link from 'next/link'
import { useState } from 'react'
import { groupThreads, type ChatThread } from '@/lib/chat'
import type { ClientSummary } from '@/lib/clients'
import TitleEditor from './TitleEditor'

// The chats, grouped Today, Yesterday and Earlier, each with its title and client, and buttons to rename and
// delete it. A chat being renamed shows its title as a box to type in.
export default function ThreadList({ threads, clients, activeId, onOpen, onDelete, onRename }: {
  threads: ChatThread[] | null
  clients: ClientSummary[] | null
  activeId: string | undefined
  onOpen: () => void           // a thread was clicked: on a phone, the list closes
  onDelete: (thread: ChatThread) => void   // asks before anything is deleted
  onRename: (thread: ChatThread, typed: string) => void
}) {
  const [renaming, setRenaming] = useState<string | null>(null)   // the id of the chat whose title is being typed
  if (threads === null) return <p className="muted small thread-empty">Loading chats…</p>
  if (!threads.length) return <p className="muted small thread-empty">Start a chat to review a client&apos;s books.</p>
  const clientName = (id: number) => clients?.find(c => c.id === id)?.name ?? ''
  return (
    <nav aria-label="Chats">
      {groupThreads(threads, new Date()).map(group => (
        <div key={group.label} className="thread-group">
          <h3 className="thread-group-label">{group.label}</h3>
          <ul className="thread-list">
            {group.threads.map(t => (
              <li key={t.id} className="thread-row">
                {renaming === t.id ? (
                  <div className="thread-link" aria-current={t.id === activeId ? 'page' : undefined}>
                    <TitleEditor title={t.title} onCancel={() => setRenaming(null)}
                                 onSave={typed => { setRenaming(null); onRename(t, typed) }} />
                    <span className="thread-client">{clientName(t.client_id)}</span>
                  </div>
                ) : (
                  <>
                    <Link href={`/chat/${t.id}`} onClick={onOpen} aria-current={t.id === activeId ? 'page' : undefined}
                          className="thread-link">
                      <span className="thread-title">{t.title}</span>
                      <span className="thread-client">{clientName(t.client_id)}</span>
                    </Link>
                    <span className="thread-actions">
                      <button type="button" className="thread-action" aria-label={`Rename chat: ${t.title}`} title="Rename chat"
                              onClick={() => setRenaming(t.id)}>
                        <PencilIcon />
                      </button>
                      <button type="button" className="thread-action thread-delete" aria-label={`Delete chat: ${t.title}`}
                              title="Delete chat" onClick={() => onDelete(t)}>
                        <BinIcon />
                      </button>
                    </span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}

// A small bin, drawn in the text's own colour.
function BinIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2.5 4.5h11M6.5 4.5v-2h3v2M4 4.5l.6 9h6.8l.6-9M6.6 7v4M9.4 7v4" />
    </svg>
  )
}

// A small pencil, drawn in the text's own colour.
function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M11 2.5l2.5 2.5L5.5 13l-3 .5.5-3zM9.5 4l2.5 2.5" />
    </svg>
  )
}
