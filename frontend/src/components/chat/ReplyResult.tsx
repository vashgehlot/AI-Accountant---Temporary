'use client'

import type { AnswerResult, TurnResult } from '@/lib/chat'
import DecisionLine from './DecisionLine'
import PostedTrialBalance from './PostedTrialBalance'
import QuestionCard from './QuestionCard'

// What one reply did, in this order and each only when present: what was sorted, what needs the person, why
// nothing was posted, and the books as posted. The narrative above it is the turn's streamed text.
export default function ReplyResult({ result, threadId, onAnswered, onSay, effects, busy }: {
  result: TurnResult
  threadId: string
  onAnswered: (a: AnswerResult) => void
  onSay: (text: string) => void
  effects: Record<string, string>   // by question id
  busy: boolean                     // a turn is running, so no card takes an answer
}) {
  const { sorted, questions, trial_balance: tb, post } = result
  return (
    <div className="review">
      {sorted.length > 0 && (
        <section className="review-sorted" aria-label="Sorted">
          <h3>✓ Sorted</h3>
          <ul className="decisions">{sorted.map(d => <DecisionLine key={d.id} decision={d} />)}</ul>
        </section>
      )}
      {questions.length > 0 && (
        <section className="review-needs" aria-label="Needs you">
          <h3>Needs you <span className="review-count">{questions.length}</span></h3>
          <ul className="questions">
            {questions.map((q, i) => (
              <QuestionCard key={q.id} question={q} number={i + 1} threadId={threadId} onAnswered={onAnswered} onSay={onSay}
                            effect={effects[q.id] || null} busy={busy} />
            ))}
          </ul>
        </section>
      )}
      {post && post.problems.length > 0 && (
        <div className="notice notice-error">
          Nothing was posted: {post.problems.join(' ')}
        </div>
      )}
      {tb && <section aria-label="Posted"><PostedTrialBalance tb={tb} /></section>}
    </div>
  )
}
