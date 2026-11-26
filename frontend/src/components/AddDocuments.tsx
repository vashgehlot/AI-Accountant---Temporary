'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { analysisForm, analyze, ApiError, getHealth, startAnalysis, waitForJob, type Transaction } from '@/lib/api'
import { addManualRows, type BankAccount, type Upload } from '@/lib/clients'
import { readingLine, requeue, sameFileAs, sameFileText, transactionCount, unsent, type FileStatus, type PickedFile,
         type ReadingFile } from '@/lib/clientRules'
import { fingerprint } from '@/lib/duplicates'

const MAX_BATCH_FILES = 20

const MARK: Record<FileStatus, string> = { waiting: '○', sending: '', reading: '', done: '✓', failed: '✖', skipped: '–', cancelled: '■' }

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// Upload, Paste and Add by hand for one year of a client. Each analysis runs as a job that
// the API saves to the year when it finishes, so onSaved reloads the year; a row added by hand is saved here, once
// the model has suggested its account. A statement goes on the account picked in Add to (the client's first by
// default): the API refuses a statement without one when the client has several. Picked files are all sent at once,
// so a refresh or another page loses none once they are sent; reading (the files the API is reading for the client)
// lists those this page isn't following, such as files sent before a refresh, and onSent has it looked at again.
export default function AddDocuments({ clientId, yearStart, bankAccounts, company, uploads, reading, onSaved, onSent }: {
  clientId: number
  yearStart: string
  bankAccounts: BankAccount[]
  company: boolean           // a limited company: the owner's own money is the Director's Loan Account
  uploads: Upload[]
  reading: ReadingFile[]
  onSaved: () => void
  onSent: () => void
}) {
  const [tab, setTab] = useState<'upload' | 'paste' | 'manual'>('upload')
  const [pasteText, setPasteText] = useState('')
  // paidFrom: one of the client's accounts by its code, or 'owner' for the owner's own money ('' : the first account).
  const [manual, setManual] = useState({ description: '', amount: '', direction: 'out' as 'in' | 'out', date: '',
                                         paidFrom: '' })
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [batch, setBatch] = useState<PickedFile[]>([])
  const [picked, setPicked] = useState('')   // the account chosen in Add to
  const [limits, setLimits] = useState({ parallel: 1, maxMb: 20 })
  const bank = bankAccounts.some(a => a.code === picked) ? picked : bankAccounts[0]?.code ?? ''
  const where = { clientId, yearStart, bankAccount: bank }
  const cancelRef = useRef(false)
  const nextId = useRef(1)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    getHealth()
      .then(h => setLimits({ parallel: Math.max(1, h.max_parallel_jobs ?? 1), maxMb: h.max_upload_mb }))
      .catch(() => { /* the header says the API is down; the defaults stand */ })
  }, [])

  const update = useCallback((id: number, patch: Partial<PickedFile>) =>
    setBatch(prev => prev.map(item => (item.id === id ? { ...item, ...patch } : item))), [])

  const analyseText = async () => {
    if (!pasteText.trim()) return
    cancelRef.current = false
    setBusy(true)
    setError('')
    setProgress('Uploading…')
    try {
      const result = await analyze(analysisForm({ text: pasteText.trim() }, where), setProgress, () => cancelRef.current)
      if (!result.transactions.length) throw new ApiError('No transactions were found in this text.', 'empty')
      setPasteText('')
      onSaved()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
      setProgress('')
    }
  }

  // A file the API refused or failed to read: skipped when it is a file the client already has (or is reading), or
  // cancelled, or failed.
  const notRead = useCallback((id: number, e: unknown) => {
    const code = e instanceof ApiError ? e.code : ''
    const status: FileStatus = code === 'same_file' ? 'skipped' : code === 'cancelled' ? 'cancelled' : 'failed'
    update(id, { status, detail: message(e) })
  }, [update])

  // Sends the waiting files one after another, then follows each until it is saved. Once sent, a file is read and
  // saved by the API whatever this page does; the API reads up to `parallel` at a time and queues the rest.
  const runBatch = async (items: PickedFile[]) => {
    const todo = items.filter(item => item.status === 'waiting')
    if (!todo.length) return
    cancelRef.current = false
    setBusy(true)
    setError('')
    setProgress(`Sending ${todo.length} file${todo.length === 1 ? '' : 's'}…`)
    const sent: { item: PickedFile; jobId: string }[] = []
    for (const item of todo) {
      if (cancelRef.current) {
        update(item.id, { status: 'cancelled', detail: 'Not read: cancelled' })
        continue
      }
      update(item.id, { status: 'sending', detail: 'Sending…' })
      try {
        const jobId = await startAnalysis(analysisForm({ file: item.file }, where))
        update(item.id, { status: 'reading', detail: 'Waiting its turn', jobId })
        sent.push({ item, jobId })
      } catch (e) {
        notRead(item.id, e)
      }
    }
    if (sent.length) onSent()
    let read = 0
    setProgress(`Reading ${sent.length} file${sent.length === 1 ? '' : 's'}, up to ${limits.parallel} at a time…`)
    await Promise.all(sent.map(async ({ item, jobId }) => {
      try {
        const result = await waitForJob(jobId, p => update(item.id, { detail: p }), () => cancelRef.current)
        const count = result.transactions.length
        if (!count) throw new ApiError('No transactions were found in this file.', 'empty')
        update(item.id, { status: 'done', detail: `${transactionCount(count)} saved` })
        onSaved()
      } catch (e) {
        notRead(item.id, e)
      }
      read++
      setProgress(`${read} of ${sent.length} files read, up to ${limits.parallel} at a time`)
    }))
    setBusy(false)
    setProgress('')
  }

  // Leaving while files are still to be sent would lose them; once sent, the API keeps reading them.
  const leaving = unsent(batch)
  useEffect(() => {
    if (!leaving) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [leaving])

  // The files being read that this page isn't following: sent before a refresh, from another page or another tab.
  const followed = new Set(batch.map(item => item.jobId).filter(Boolean))
  const elsewhere = reading.filter(file => !followed.has(file.job_id) && (!file.year_start || file.year_start === yearStart))

  const pickFiles = async (files: FileList | null) => {
    const chosen = Array.from(files ?? [])
    if (fileInput.current) fileInput.current.value = ''   // lets the same files be chosen again
    if (!chosen.length) return
    const hashes = await Promise.all(chosen.slice(0, MAX_BATCH_FILES).map(fingerprint))
    const items: PickedFile[] = []
    hashes.forEach((hash, n) => {
      const file = chosen[n]
      // A file already saved for this client, or picked twice, is not read again: its rows would be booked twice.
      const saved = sameFileAs(hash, uploads)
      const twice = hash ? items.find(item => item.hash === hash) : undefined
      // Size is checked here because the Next proxy cuts oversized bodies instead of refusing them.
      const tooBig = file.size > limits.maxMb * 1024 * 1024
      const detail = saved ? sameFileText(saved)
        : twice ? `Skipped: same file as ${twice.file.name} in this upload`
        : tooBig ? `Larger than the ${limits.maxMb} MB limit: split it and upload the parts` : 'Waiting'
      items.push({ id: nextId.current++, file, hash, status: saved || twice || tooBig ? 'skipped' : 'waiting', detail })
    })
    setBatch(items)
    setError(chosen.length > MAX_BATCH_FILES
      ? `Only the first ${MAX_BATCH_FILES} files were added; upload the other ${chosen.length - MAX_BATCH_FILES} next.`
      : '')
    runBatch(items)
  }

  // Files saved after all, just as a cancel arrived, are skipped rather than read and booked again.
  const retry = () => {
    const again = requeue(batch, uploads)
    setBatch(again)
    runBatch(again)
  }

  // A row typed by hand: the model only suggests its account; the ledger splits VAT like any other row's.
  const addByHand = async () => {
    const amount = Math.abs(Number(manual.amount))
    const description = manual.description.trim()
    if (!description || !Number.isFinite(amount) || amount <= 0 || !manual.date) return
    // Cash and anything else not through the bank is the owner's money: the bank's balance is left as its statement
    // has it. Otherwise the row moves money on the account chosen.
    const through = manual.paidFrom || bankAccounts[0]?.code || 'owner'
    const owner = through === 'owner' ? (company ? '2250' : '3010') : null
    cancelRef.current = false
    setBusy(true)
    setError('')
    setProgress('Asking the AI model for an account…')
    try {
      const verb = manual.direction === 'in' ? 'received' : 'paid'
      const result = await analyze(analysisForm({ text: `${description} - ${verb} GBP ${amount}` }), setProgress, () => cancelRef.current)
      const suggested = result.transactions[0]
      const row: Transaction = {
        date: manual.date, description, direction: manual.direction, gross: amount.toFixed(2), vat: null,
        vat_treatment: null, vat_posted: null, net: null, account_code: suggested?.account_code ?? '9998',
        contra_account_code: owner, bank_account: owner ? null : through,
        currency: 'GBP', source: 'manual', method: 'user', evidence: null,
        document_type: 'receipt',
        issues: suggested
          ? suggested.issues.filter(i => i.code === 'account_not_recognised' || i.code === 'account_unclear')
          : [{ code: 'account_not_recognised', severity: 'warning', message: 'No account suggested; posted to Suspense.' }],
      }
      await addManualRows(clientId, [row], yearStart)
      onSaved()
      setManual(m => ({ ...m, description: '', amount: '' }))
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
      setProgress('')
    }
  }

  const canRetry = !busy && batch.some(item => item.status === 'failed' || item.status === 'cancelled')
  const closed = busy   // nothing new can be started while files are being read
  return (
    <section className="card section">
      <div className="section-head">
        <h2>Add documents</h2>
        <span className="muted small">Invoices, receipts, bank statements and expense claims</span>
      </div>
      <div className="tabs" role="tablist">
        {(['upload', 'paste', 'manual'] as const).map(t => (
          <button key={t} type="button" role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t === 'upload' ? 'Upload files' : t === 'paste' ? 'Paste text' : 'Add by hand'}
          </button>
        ))}
      </div>
      <div className="add-to">
        {bankAccounts.length > 1 && (
          <label className="year-picker">
            <span>Add to</span>
            <select className="input" value={bank} aria-label="Bank account for statements" onChange={e => setPicked(e.target.value)}>
              {bankAccounts.map(a => <option key={a.code} value={a.code}>{a.name}</option>)}
            </select>
          </label>
        )}
      </div>
      {tab === 'upload' && (
        <>
          <input ref={fileInput} type="file" multiple hidden onChange={e => pickFiles(e.target.files)}
                 accept=".csv,.tsv,.txt,.xlsx,.xls,.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff" />
          <div className={`dropzone${dragOver ? ' drag-over' : ''}`} role="button" tabIndex={0}
               onClick={() => { if (!closed) fileInput.current?.click() }}
               onKeyDown={e => { if ((e.key === 'Enter' || e.key === ' ') && !closed) fileInput.current?.click() }}
               onDragOver={e => { e.preventDefault(); setDragOver(true) }}
               onDragLeave={() => setDragOver(false)}
               onDrop={e => { e.preventDefault(); setDragOver(false); if (!closed) pickFiles(e.dataTransfer.files) }}>
            <strong>Drop files here or click to choose</strong>
            Up to {MAX_BATCH_FILES} at a time: PDFs, photos, CSV and Excel files, up to {limits.maxMb} MB each
          </div>
        </>
      )}
      {tab === 'paste' && (
        <>
          <textarea className="input" value={pasteText} onChange={e => setPasteText(e.target.value)} aria-label="Text to analyse"
                    placeholder={'BT Business broadband, 05/09/2026, £72.00 including £12.00 VAT\nBank: 25/09/2026 BT GROUP PLC DD -72.00'} />
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={analyseText} disabled={closed || !pasteText.trim()}>
              Analyse
            </button>
          </div>
        </>
      )}
      {tab === 'manual' && (
        <>
          <div className="manual-grid">
            <label className="field">
              <span>Date</span>
              <input className="input" type="date" value={manual.date}
                     onChange={e => setManual(m => ({ ...m, date: e.target.value }))} />
            </label>
            <label className="field">
              <span>Description</span>
              <input className="input" value={manual.description} placeholder="Office chair"
                     onChange={e => setManual(m => ({ ...m, description: e.target.value }))} />
            </label>
            <label className="field">
              <span>Amount (£)</span>
              <input className="input" type="number" step="0.01" min="0" value={manual.amount} placeholder="120.00"
                     onChange={e => setManual(m => ({ ...m, amount: e.target.value }))} />
            </label>
            <label className="field">
              <span>Money</span>
              <select className="input" value={manual.direction}
                      onChange={e => setManual(m => ({ ...m, direction: e.target.value as 'in' | 'out' }))}>
                <option value="out">Paid out</option>
                <option value="in">Received</option>
              </select>
            </label>
            <label className="field">
              <span>{manual.direction === 'in' ? 'Paid into' : 'Paid from'}</span>
              <select className="input" value={manual.paidFrom || bankAccounts[0]?.code || 'owner'}
                      onChange={e => setManual(m => ({ ...m, paidFrom: e.target.value }))}>
                {bankAccounts.map(a => <option key={a.code} value={a.code}>{a.name}</option>)}
                <option value="owner">{company ? "Director's own money or cash" : "Owner's own money or cash"}</option>
              </select>
            </label>
          </div>
          <p className="muted small">
            A row on a bank account or card should also be on its statement: add cash and anything paid personally
            as the {company ? "director's" : "owner's"} own money, so the bank still agrees with its statement.
          </p>
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={addByHand}
                    disabled={closed || !manual.description.trim() || !(Number(manual.amount) > 0) || !manual.date}>
              Add row
            </button>
          </div>
        </>
      )}
      {busy && (
        <div className="progress">
          <span className="spinner" aria-hidden="true" />
          <span>{progress || 'Working…'}</span>
          <button type="button" className="btn btn-ghost" onClick={() => { cancelRef.current = true; setProgress('Cancelling…') }}>
            Cancel
          </button>
        </div>
      )}
      {error && <div className="notice notice-error">{error}</div>}
      {batch.length > 0 && (
        <ul className="batch">
          {batch.map(item => (
            <li key={item.id} className={`batch-${item.status}`}>
              <span aria-hidden="true">{item.status === 'reading' || item.status === 'sending' ? <span className="spinner" /> : MARK[item.status]}</span>
              <span className="batch-name" title={item.file.name}>{item.file.name}</span>
              <span className="batch-detail" title={item.detail}>{item.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {elsewhere.length > 0 && (
        <ul className="batch" aria-label="Files still being read">
          {elsewhere.map(file => (
            <li key={file.job_id} className="batch-reading">
              <span aria-hidden="true"><span className="spinner" /></span>
              <span className="batch-name" title={file.name}>{file.name}</span>
              <span className="batch-detail">{readingLine(file)}: saved here when it is read</span>
            </li>
          ))}
        </ul>
      )}
      {canRetry && (
        <div className="form-actions"><button type="button" className="btn" onClick={retry}>Retry failed files</button></div>
      )}
    </section>
  )
}
