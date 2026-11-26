'use client'

import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { ApiError } from '@/lib/api'
import { getYears } from '@/lib/clients'
import { latestYear, sectionHref } from '@/lib/years'

// A client's address on its own opens the latest year's Overview.
export default function ClientRedirect() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const clientId = Number(params.id)
  const [problem, setProblem] = useState<{ missing: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!Number.isInteger(clientId) || clientId < 1) {
      setProblem({ missing: true, text: '' })
      return
    }
    getYears(clientId)
      .then(years => router.replace(sectionHref(clientId, latestYear(years).start, 'overview')))
      .catch((e: unknown) => setProblem({
        missing: e instanceof ApiError && e.code === 'not_found', text: e instanceof Error ? e.message : String(e),
      }))
  }, [clientId, router])

  if (!problem) return <p className="muted">Loading…</p>
  if (!problem.missing) return <div className="notice notice-error">{problem.text}</div>
  return (
    <div className="empty card">
      <h1>Client not found</h1>
      <p className="muted">It may never have existed, or the link is wrong.</p>
      <Link href="/" className="btn">Back to clients</Link>
    </div>
  )
}
