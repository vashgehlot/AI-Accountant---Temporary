'use client'

import { useEffect } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import type { SavedRow, Upload } from '@/lib/clients'
import { longDate, money } from '@/lib/ledger'
import { canShow, fileHref, isPdf, linesNote } from '@/lib/suggestions'

// One document in the panel: its upload, the rows read from it, the row to mark (none: no row), and what the AI
// quoted from it.
export interface PanelDocument {
  upload: Upload
  rows: SavedRow[]
  rowId: number | null
  quotes: string[]
}

// The documents a card is about, or the upload being looked at, beside the list, one under another: for each, what
// the AI quoted from it, then the file itself when a browser can show it (a PDF or an image), or else the lines that
// were read from it, with its row marked.
export default function DocumentPanel({ documents, onClose }: { documents: PanelDocument[]; onClose: () => void }) {
  const { client } = useClientYear()
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const names = documents.map(d => d.upload.name)
  const several = documents.length > 1
  return (
    <aside className={several ? 'document-panel document-panel-several' : 'document-panel'} aria-label={`${several ? 'Documents' : 'Document'}: ${names.join(', ')}`}>
      <div className="document-panel-head">
        <strong>{several ? `${documents.length} documents` : names[0]}</strong>
        {!several && documents[0]?.upload.sha256 && (
          <a className="link-btn" href={fileHref(client.id, documents[0].upload.id)}>Download</a>
        )}
        <button type="button" className="btn btn-small" onClick={onClose}>Close</button>
      </div>
      {documents.map(doc => (
        <section key={doc.upload.id} className="document-panel-doc" aria-label={several ? doc.upload.name : undefined}>
          {several && (
            <div className="document-panel-head">
              <strong>{doc.upload.name}</strong>
              {doc.upload.sha256 && <a className="link-btn" href={fileHref(client.id, doc.upload.id)}>Download</a>}
            </div>
          )}
          <OneDocument clientId={client.id} doc={doc} />
        </section>
      ))}
    </aside>
  )
}

export function OneDocument({ clientId, doc: { upload, rows, rowId, quotes } }: { clientId: number; doc: PanelDocument }) {
  const kept = !!upload.sha256
  const shown = kept && canShow(upload.name)
  return (
    <>
      {quotes.map((quote, i) => <blockquote key={i} className="evidence"><p>“{quote}”</p></blockquote>)}
      {shown && isPdf(upload.name) && <iframe title={upload.name} src={fileHref(clientId, upload.id, true)} />}
      {shown && !isPdf(upload.name) && (
        // eslint-disable-next-line @next/next/no-img-element -- the client's own file, served by the API as it was sent
        <img alt={upload.name} src={fileHref(clientId, upload.id, true)} />
      )}
      {!shown && (
        <>
          <p className="muted small">{linesNote(upload)}</p>
          <table className="table document-lines">
            <thead><tr><th>Date</th><th>Description</th><th className="num">Amount</th></tr></thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.id} aria-current={row.id === rowId ? 'true' : undefined}>
                  <td>{row.date ? longDate(row.date) : 'No date'}</td>
                  <td>{row.description}</td>
                  <td className="num">{money(row.gross)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  )
}
