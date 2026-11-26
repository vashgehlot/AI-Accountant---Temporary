// A client's years and sections: the links, the year picker's words and which year is the current one. Kept apart
// from the network so node --test can run them.
import type { Year } from './clients'

export const SECTIONS = [
  { slug: 'overview', title: 'Overview' },
  { slug: 'ai-review', title: 'AI review' },
  { slug: 'documents', title: 'Documents' },
  { slug: 'bank', title: 'Bank' },
  { slug: 'invoices', title: 'Invoices' },
  { slug: 'transactions', title: 'Transactions' },
  { slug: 'trial-balance', title: 'Trial balance' },
] as const

export type SectionSlug = (typeof SECTIONS)[number]['slug']

export const isSection = (slug: string): slug is SectionSlug => SECTIONS.some(s => s.slug === slug)

export const sectionHref = (clientId: number, yearStart: string, slug: SectionSlug) =>
  `/clients/${clientId}/${yearStart}/${slug}`

// The year that ends last (ISO dates compare as text).
export const latestYear = (years: Year[]): Year => years.reduce((a, b) => (b.end > a.end ? b : a))

// The year being worked on: the one that holds the day (an ISO date) when it holds rows; else, books being caught up,
// the earliest open year that does (years are closed in order, and a few papers dated after its end are in the next);
// else the one that holds the day, or the latest when none does.
export function currentYear(years: Year[], today: string): Year {
  const holding = years.find(y => y.start <= today && today <= y.end)
  if (holding && (holding.rows ?? 0) > 0) return holding
  const worked = years.filter(y => !y.closed && (y.rows ?? 0) > 0)
  return worked.length ? worked.reduce((a, b) => (b.start < a.start ? b : a)) : holding ?? latestYear(years)
}

// "Year to 31 Mar 2026", and " · closed" once the year is closed.
export const yearOption = (year: Year): string => (year.closed ? `${year.label} · closed` : year.label)

// A day as the API writes it ("2026-10-30"), from the computer's own calendar.
export const isoDay = (day: Date): string =>
  `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
