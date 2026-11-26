'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useClientYear } from '@/components/ClientYearContext'
import AiReviewSection from '@/components/AiReviewSection'
import BankSection from '@/components/BankSection'
import DocumentsSection from '@/components/DocumentsSection'
import InvoicesSection from '@/components/InvoicesSection'
import OverviewSection from '@/components/OverviewSection'
import TransactionsSection from '@/components/TransactionsSection'
import TrialBalancePanel from '@/components/TrialBalancePanel'
import { isSection, sectionHref } from '@/lib/years'

// One section of a client's year.
export default function SectionPage() {
  const params = useParams<{ section: string }>()
  const { client, year } = useClientYear()

  if (!isSection(params.section)) {
    return (
      <div className="empty card">
        <h2>Section not found</h2>
        <p className="muted">There is no section called “{params.section}”.</p>
        <Link href={sectionHref(client.id, year.start, 'overview')} className="btn">Go to Overview</Link>
      </div>
    )
  }
  if (params.section === 'overview') return <OverviewSection />
  if (params.section === 'ai-review') return <AiReviewSection />
  if (params.section === 'documents') return <DocumentsSection />
  if (params.section === 'bank') return <BankSection />
  if (params.section === 'invoices') return <InvoicesSection />
  if (params.section === 'transactions') return <TransactionsSection />
  return <TrialBalancePanel />
}
