// What a waiting suggestion would change, which suggestions make the same change, and which document a card can
// show beside it: the rules behind the AI review page's suggestions. Kept apart from the network so node --test can
// run it.
import type { Decision } from './chat.ts'
import { changedFields } from './chat.ts'
import type { Upload } from './clients'

const none = (value: string) => (value === '—' ? 'none' : value)

// One line for each field a suggestion changes: "Date: none → 2 Sep 2026", or "Row 12 · Account: 7500 → 7400" when
// it changes more than one row. At most `most` lines; `more` is how many were left out.
export function changeLines(d: Decision, most = 4): { lines: string[]; more: number } {
  const changes = changedFields(d)
  const several = new Set(changes.map(c => c.row)).size > 1
  const lines = changes.map(c => `${several ? `Row ${c.row} · ` : ''}${c.field}: ${none(c.before)} → ${none(c.after)}`)
  return { lines: lines.slice(0, most), more: Math.max(0, lines.length - most) }
}

// Suggestions that make the same change, so they can be applied together: the same kind of change to the same new
// values, on different rows. Only groups of two or more, in the order their first suggestion is listed. A suggestion
// that changes no field (it keeps one of two records, say) is its own decision and joins none.
export interface FixGroup { key: string; label: string; suggestions: Decision[] }
export function sameFixGroups(suggestions: Decision[]): FixGroup[] {
  const groups = new Map<string, { to: string[]; suggestions: Decision[] }>()
  for (const d of suggestions) {
    const to = [...new Set(changedFields(d).map(c => `${c.field}=${none(c.after)}`))].sort()
    if (!to.length) continue
    const key = `${d.action}|${to.join('|')}`
    const group = groups.get(key) ?? { to, suggestions: [] }
    group.suggestions.push(d)
    groups.set(key, group)
  }
  return [...groups.entries()].filter(([, g]) => g.suggestions.length > 1).map(([key, g]) => {
    const rows = new Set(g.suggestions.flatMap(d => d.row_ids)).size
    return { key, label: `${g.to.map(t => t.replace('=', ' → ')).join(', ')} on ${rows} rows`, suggestions: g.suggestions }
  })
}

// Whether a browser can show the file in the page, by its name: a PDF or an image. The API sends only these for
// showing (SHOWN_IN_PAGE in server.py), whatever is asked.
const SHOWN = /\.(pdf|png|jpe?g|webp|gif)$/i
export const canShow = (name: string): boolean => SHOWN.test(name)
export const isPdf = (name: string): boolean => /\.pdf$/i.test(name)

// Whether an upload has a document to look at: any but rows typed in by hand.
export const viewable = (upload: Upload): boolean => upload.kind !== 'manual'

// The upload a row's document can be viewed from; none for a row typed in by hand.
export function documentOf(row: { upload_id: number }, uploads: Upload[]): Upload | null {
  const upload = uploads.find(u => u.id === row.upload_id)
  return upload && viewable(upload) ? upload : null
}

// Said over the lines read from an upload when its file isn't shown: why there is no file. A split (rows a person split
// in two) keeps none of its own, but the upload it was split off does, so it never says the file was lost.
export function linesNote(upload: Upload): string {
  if (upload.kind === 'split') {
    return `Split off ${upload.name.replace(/ \(split\)$/, '')}, which holds the file. These are the lines split off it.`
  }
  if (upload.kind === 'text' && !upload.sha256 && upload.name === 'Pasted text') return 'Pasted as text. These are the lines read from it.'
  return upload.sha256 ? 'This kind of file can’t be shown here. These are the lines read from it.'
    : 'The original file wasn’t kept. These are the lines read from it.'
}

// Every document a card is about, each once, with the first of the card's rows read from it: its own row's first,
// then those of the rows its issues, suggestions and questions name, so a card asking whether two records are one
// shows both. A row typed in by hand, or no longer among the rows, adds none.
interface Named { id: number; upload_id: number }
export function cardDocuments(
  card: { row: Named | null; issues: { related?: number[] }[]; suggestions: { row_ids: number[] }[]; questions: { row_ids: number[] }[] },
  rows: Named[], uploads: Upload[],
): { upload: Upload; rowId: number }[] {
  const ids = [...(card.row ? [card.row.id] : []), ...card.issues.flatMap(i => i.related ?? []),
               ...card.suggestions.flatMap(s => s.row_ids), ...card.questions.flatMap(q => q.row_ids)]
  const found = new Map<number, { upload: Upload; rowId: number }>()
  for (const id of ids) {
    const row = id === card.row?.id ? card.row : rows.find(r => r.id === id)
    const upload = row && documentOf(row, uploads)
    if (row && upload && !found.has(upload.id)) found.set(upload.id, { upload, rowId: row.id })
  }
  return [...found.values()]
}

// The original file of an upload: as a download, or (show) for the page to show in place.
export const fileHref = (clientId: number, uploadId: number, show = false): string =>
  `/api/clients/${clientId}/uploads/${uploadId}/file${show ? '?show=1' : ''}`
