'use client'

import { useRef, useState } from 'react'
import { TITLE_MAX } from '@/lib/chat'

// A chat's title as a box to type in: Enter, or clicking away, keeps what was typed; Escape leaves the title alone.
export default function TitleEditor({ title, onSave, onCancel }: {
  title: string
  onSave: (typed: string) => void
  onCancel: () => void
}) {
  const [typed, setTyped] = useState(title)
  const ended = useRef(false)                  // Enter or Escape removes the box, which must not then save on blur
  const end = (save: boolean) => {
    if (ended.current) return
    ended.current = true
    if (save) onSave(typed)
    else onCancel()
  }
  return (
    <input className="input title-editor" value={typed} maxLength={TITLE_MAX} aria-label="Chat title" autoFocus
           onFocus={e => e.target.select()} onChange={e => setTyped(e.target.value)} onBlur={() => end(true)}
           onKeyDown={e => {
             if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); end(true) }
             if (e.key === 'Escape') end(false)
           }} />
  )
}
