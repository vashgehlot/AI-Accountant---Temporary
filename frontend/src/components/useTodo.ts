'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import { clientQuestions, type Decision, type Question } from '@/lib/chat'
import { DOCUMENT_TYPES } from '@/lib/clientRules'
import { listReviews, listSuggestions, newestFirst, type ReviewDetail } from '@/lib/reviews'
import { needCount, openQuestions, todoCards, type TodoCard } from '@/lib/todo'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// What is left to do in the client's year, worked out once for every page that shows it: the AI review's cards and
// how many of them need the person. Loaded again whenever the year's rows are; until it is, cards and need are null.
export function useTodo() {
  const { client, year, ledger } = useClientYear()
  const [runs, setRuns] = useState<ReviewDetail[] | null>(null)
  const [suggestions, setSuggestions] = useState<Decision[]>([])   // what waits for the person, the rules' too
  const [questions, setQuestions] = useState<Question[]>([])       // the client's questions, the books' own among them
  const [error, setError] = useState('')
  const latest = useRef(0)   // the newest load: an answer overtaken by a later one is dropped

  // Loaded again whenever the year's rows are (a change, a poll); true when this or a later load got through.
  const reload = useCallback(async (): Promise<boolean> => {
    const ticket = ++latest.current
    try {
      const [reviews, waiting, asked] = await Promise.all([
        listReviews(client.id, year.start), listSuggestions(client.id, year.start), clientQuestions(client.id),
      ])
      if (ticket !== latest.current) return true
      setRuns(newestFirst(reviews))
      setSuggestions(waiting)
      setQuestions(asked)
      setError('')
      return true
    } catch (e) {
      if (ticket !== latest.current) return true
      setError(message(e))
      return false
    }
  }, [client.id, year.start])

  useEffect(() => { reload() }, [reload, ledger])

  // A problem with a whole document is named by its file, "Mark october expenses.xlsx, expense claim".
  const cards = useMemo((): TodoCard[] | null => {
    if (!runs) return null
    const names = new Map(ledger.uploads.map(u => [u.id, u.name]))
    return todoCards(ledger.transactions, suggestions, openQuestions(runs, questions, year.start), row =>
      `${names.get(row.upload_id) ?? 'Document'}, ${(DOCUMENT_TYPES[row.document_type ?? 'receipt'] ?? 'document').toLowerCase()}`)
  }, [ledger.transactions, ledger.uploads, suggestions, runs, questions, year.start])

  return { cards, need: cards ? needCount(cards) : null, runs, suggestions, questions, reload, error }
}
