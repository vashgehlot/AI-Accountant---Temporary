'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import DecisionLine from '@/components/chat/DecisionLine'
import QuestionCard from '@/components/chat/QuestionCard'
import { useClientYear } from '@/components/ClientYearContext'
import IssueList from '@/components/IssueList'
import type { AnswerResult, Decision } from '@/lib/chat'
import type { AccountChoice, RowChange, SavedRow } from '@/lib/clients'
import { acceptChange, apartChange, askAbout, claimLineOf, issueFixes, takesLines } from '@/lib/ledger'
import type { Answerer } from '@/lib/reviews'
import { cardDocuments, changeLines } from '@/lib/suggestions'
import { groupOf, type TodoCard } from '@/lib/todo'
import { sectionHref } from '@/lib/years'

// What needs the person, one card each: a row with what is wrong with it, a document whose total doesn't add up, or
// a question or a suggestion on its own. A card holds everything that settles it: the same issue list, with the same
// controls, as the Transactions page; the change the AI suggests, with Apply; and the question it asks, with its
// answer. A closed year or an archived client shows the cards with no control that changes anything.
export default function TodoList({ cards, accounts, working, refused, answerer, viewing, onView, onChange, onApply, onEdit, onAddLine, onAnswered, onSay }: {
  cards: TodoCard[]
  accounts: AccountChoice[]            // the accounts a row can be coded to, read once for every list
  working: string                      // the suggestion being applied, 'all', or ''
  refused: Record<string, string>      // why an Apply didn't go through, by suggestion
  answerer: Answerer
  viewing: string | null               // the key of the card whose documents are open beside the list
  onView: (card: TodoCard) => void     // open the card's documents beside the list
  onChange: (rowId: number, change: RowChange) => void
  onApply: (suggestion: Decision) => void
  onEdit: (row: SavedRow) => void
  onAddLine: (row: SavedRow) => void
  onAnswered: (a: AnswerResult) => void
  onSay: (text: string) => void
}) {
  const { client, year, ledger } = useClientYear()
  const router = useRouter()
  const readOnly = year.closed || client.archived
  const rows = ledger.transactions
  // A card's row on the Transactions page, beside the rows its issues name.
  const rowHref = (row: SavedRow, document: boolean) =>
    `${sectionHref(client.id, year.start, 'transactions')}?row=${row.id}${document ? '&lines=1' : ''}`
  const askHref = (row: SavedRow) => readOnly ? undefined
    : (issue: TodoCard['issues'][number]) => `/chat?client=${client.id}&ask=${encodeURIComponent(askAbout(row, issue))}`

  return (
    <ul className="todo-list">
      {cards.map(card => {
        const row = card.row
        const documents = cardDocuments(card, rows, ledger.uploads).length
        return (
          <li key={card.key} className={`todo-card todo-in-${groupOf(card)}${card.waiting ? ' todo-waiting' : ''}${viewing === card.key ? ' todo-viewing' : ''}`}>
            <div className="todo-head">
              <span className="badge badge-muted">{card.tag}</span>
              {/* A question about no row is its own title: its card says it once, below. */}
              {(row || !card.questions.length) && <strong>{card.title}</strong>}
              {card.waiting && <span className="badge badge-warn">Waiting on you</span>}
              {row && <Link href={rowHref(row, card.kind === 'document')} className="small">{card.kind === 'document' ? 'Show its lines' : 'Show row'}</Link>}
              {row && documents > 0 && (
                <button type="button" className="link-btn small" aria-pressed={viewing === card.key} onClick={() => onView(card)}>
                  {documents === 1 ? 'View document' : documents === 2 ? 'View both documents' : `View ${documents} documents`}
                </button>
              )}
            </div>
            {row && card.kind === 'row' && (
              <IssueList issues={card.issues} onShowBoth={() => router.push(rowHref(row, false))}
                         onNotSame={readOnly ? undefined : related => onChange(row.id, apartChange(row, related))}
                         onAccept={readOnly ? undefined : code => onChange(row.id, acceptChange(row, code))}
                         fixesOf={readOnly ? undefined : issue => issueFixes(row, issue, claimLineOf(row, rows))}
                         onFix={change => onChange(row.id, change)} onEdit={() => onEdit(row)}
                         accounts={accounts} documentsHref={sectionHref(client.id, year.start, 'documents')}
                         askHref={askHref(row)} />
            )}
            {row && card.kind === 'document' && (
              <IssueList issues={card.issues} onShowBoth={() => router.push(rowHref(row, true))}
                         onAddLine={!readOnly && takesLines(row) ? () => onAddLine(row) : undefined}
                         fixesOf={readOnly ? undefined : issue => issueFixes(row, issue)}
                         onFix={change => onChange(row.id, change)} askHref={askHref(row)} />
            )}
            {card.suggestions.map(d => {
              const change = changeLines(d)
              return (
              <div key={d.id} className="todo-suggestion">
                <ul className="decisions"><DecisionLine decision={d} /></ul>
                {/* What it would change, without opening it. */}
                {change.lines.map((line, i) => <p key={i} className="todo-change mono small">{line}</p>)}
                {change.more > 0 && <p className="todo-change muted small">and {change.more} more</p>}
                <div className="question-row">
                  <button type="button" className="btn btn-small" disabled={readOnly || !!working} onClick={() => onApply(d)}>
                    {working === d.id ? 'Applying…' : 'Apply'}
                  </button>
                  <span className="muted small">A suggestion: nothing has changed yet.</span>
                  {refused[d.id] && <span className="field-error">{refused[d.id]}</span>}
                </div>
              </div>
              )
            })}
            {card.questions.length > 0 && (
              <ul className="questions">
                {card.questions.map((q, i) => (
                  <QuestionCard key={q.id} question={q} number={i + 1} answerer={answerer} onAnswered={onAnswered} onSay={onSay}
                                effect={null} busy={readOnly} />
                ))}
              </ul>
            )}
          </li>
        )
      })}
    </ul>
  )
}
