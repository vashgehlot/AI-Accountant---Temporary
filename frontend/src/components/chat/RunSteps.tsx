'use client'

import type { Step } from '@/lib/chat'

const MARK = { done: '✓', failed: '✖' } as const

// A turn's steps, folded under one line: "Working on it…" with a spinner while it runs, the count once it ends.
export default function RunSteps({ steps, status, running }: { steps: Step[]; status: string; running: boolean }) {
  if (!running && !steps.length) return null
  const label = running ? status || 'Working on it…' : `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}`
  return (
    <details className="run-steps" open={running || undefined}>
      <summary>
        {running && <span className="spinner" aria-hidden="true" />} {label}
      </summary>
      {steps.length > 0 && (
        <ul>
          {steps.map(s => (
            <li key={s.id} className={`run-step run-step-${s.state}`}>
              <span className="run-step-mark" aria-hidden="true">
                {s.state === 'running' ? <span className="spinner" /> : MARK[s.state]}
              </span>
              {s.text}
            </li>
          ))}
        </ul>
      )}
    </details>
  )
}
