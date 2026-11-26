'use client'

import Image from 'next/image'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useConfirm } from '@/components/ConfirmDialog'
import { getHealth, type Health } from '@/lib/api'
import { resetDemo } from '@/lib/chat'
import { startTheme, THEME_KEY, type Theme } from '@/lib/theme'
import logo from '@/assets/acting-office-logo.png'

// The bar on every page: the Acting Office logo and the app's name (back to the clients), the Clients and Chat links,
// whether the AI model can be reached, Reset demo when the API runs the demo, and the light/dark switch, with room on the right for the Agent button. The switch's choice is kept in this browser; the layout applies it before painting.
export default function AppHeader() {
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState('')
  const [theme, setTheme] = useState<Theme>('light')
  const [resetting, setResetting] = useState(false)
  const pathname = usePathname()
  const { ask, dialog } = useConfirm()

  useEffect(() => {
    let alive = true
    const check = () => getHealth()
      .then(h => { if (alive) { setHealth(h); setHealthError('') } })
      .catch((e: unknown) => { if (alive) { setHealth(null); setHealthError(e instanceof Error ? e.message : String(e)) } })
    check()
    const timer = setInterval(check, 30_000)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  useEffect(() => {
    let saved: string | null = null
    try { saved = localStorage.getItem(THEME_KEY) } catch { /* storage blocked: follow the computer */ }
    setTheme(startTheme(saved, window.matchMedia('(prefers-color-scheme: dark)').matches))
  }, [])

  const flip = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try { localStorage.setItem(THEME_KEY, next) } catch { /* applied, just not remembered */ }
    setTheme(next)
  }

  // Puts the demo client back as it started, with no chats, decisions or postings, and opens a new chat.
  const reset = async () => {
    if (!(await ask('Reset the demo? Every chat, decision and posting goes, and the demo client is put back as it started.',
                    'Reset demo'))) return
    setResetting(true)
    try {
      await resetDemo()
      window.location.assign('/chat')
    } catch (e) {
      setResetting(false)
      setHealthError(e instanceof Error ? e.message : String(e))
    }
  }

  const inChat = pathname?.startsWith('/chat') ?? false
  const online = !!health?.model_available
  const status = health ? (online ? `AI online · ${health.model}` : 'AI offline') : healthError ? 'API offline' : 'Checking…'
  const switchTo = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
  const brand = (
    <>
      {/* Served as it is: the optimiser would soften a logo this small. */}
      <Image src={logo} alt="Acting Office" className="brand-logo" unoptimized loading="eager" />
      <span className="brand-name">Super Accountant</span>
    </>
  )
  return (
    <>
      <header className="app-header">
        <Link href="/" className="brand">{brand}</Link>
        <nav className="header-nav" aria-label="Main">
          <Link href="/" aria-current={inChat ? undefined : 'page'}>Clients</Link>
          <Link href="/chat" aria-current={inChat ? 'page' : undefined}>Chat</Link>
        </nav>
        <div className="header-end">
          <span className={`ai-status ${online ? 'ai-on' : 'ai-off'}`} title={health?.ai_error || healthError}>
            <span className="ai-status-text">{status}</span>
          </span>
          {health?.demo && (
            <button type="button" className="bar-btn" onClick={reset} disabled={resetting}>
              {resetting ? 'Resetting…' : 'Reset demo'}
            </button>
          )}
          <button type="button" className="icon-btn" onClick={flip} aria-label={switchTo} title={switchTo}>
            {theme === 'dark' ? '☀' : '☾'}
          </button>
          {/* Kept empty for the Agent button that a later project adds. */}
          <div className="agent-slot" />
        </div>
      </header>
      {dialog}
    </>
  )
}
