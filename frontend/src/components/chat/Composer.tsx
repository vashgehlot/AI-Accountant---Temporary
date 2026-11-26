'use client'

import { useRef, useState, type KeyboardEvent } from 'react'
import { looksLikeStatement } from '@/lib/chat'
import type { BankAccount } from '@/lib/clients'

export interface Attached { id: number; file: File; bank: string }   // bank: '' for the client's first account

// The message box: text, the paperclip and drag and drop. A statement's chip picks the bank account it goes on when
// the client has more than one. While a turn runs, Send becomes Stop.
export default function Composer({ text, onText, bankAccounts, running, onSend, onStop }: {
  text: string
  onText: (text: string) => void
  bankAccounts: BankAccount[]
  running: boolean
  onSend: (text: string, files: File[], bankAccounts: string[]) => void
  onStop: () => void
}) {
  const [attached, setAttached] = useState<Attached[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const nextId = useRef(1)

  const add = (files: FileList | null) => {
    if (!files?.length) return
    const added = Array.from(files, file => ({ id: nextId.current++, file, bank: '' }))
    setAttached(prev => [...prev, ...added])
  }
  const send = () => {
    if (running || (!text.trim() && !attached.length)) return
    onSend(text.trim() || 'Review the documents I\'m adding', attached.map(a => a.file), attached.map(a => a.bank))
    setAttached([])
    onText('')
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }

  return (
    <form className={dragOver ? 'composer drag-over' : 'composer'} onSubmit={e => { e.preventDefault(); send() }}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }} onDragLeave={() => setDragOver(false)}
          onDrop={e => { e.preventDefault(); setDragOver(false); add(e.dataTransfer.files) }}>
      {attached.length > 0 && (
        <ul className="file-chips">
          {attached.map(a => (
            <li key={a.id} className="file-chip">
              <span className="file-chip-name" title={a.file.name}>{a.file.name}</span>
              {bankAccounts.length > 1 && looksLikeStatement(a.file.name) && (
                <select className="file-chip-bank" value={a.bank} aria-label={`Bank account for ${a.file.name}`}
                        onChange={e => setAttached(prev => prev.map(x => (x.id === a.id ? { ...x, bank: e.target.value } : x)))}>
                  {bankAccounts.map((b, i) => <option key={b.code} value={i === 0 ? '' : b.code}>{b.name}</option>)}
                </select>
              )}
              <button type="button" className="file-chip-remove" aria-label={`Remove ${a.file.name}`}
                      onClick={() => setAttached(prev => prev.filter(x => x.id !== a.id))}>×</button>
            </li>
          ))}
        </ul>
      )}
      <div className="composer-row">
        <input ref={fileInput} type="file" multiple hidden onChange={e => { add(e.target.files); e.target.value = '' }} />
        <button type="button" className="btn btn-ghost composer-clip" aria-label="Add documents" title="Add documents"
                onClick={() => fileInput.current?.click()}>📎</button>
        <textarea className="input composer-text" rows={1} value={text} onChange={e => onText(e.target.value)} onKeyDown={onKey}
                  placeholder="Message, or drop documents here" aria-label="Message" />
        {running
          ? <button type="button" className="btn" onClick={onStop}>Stop</button>
          : <button type="submit" className="btn btn-primary" disabled={!text.trim() && !attached.length}>Send</button>}
      </div>
    </form>
  )
}
