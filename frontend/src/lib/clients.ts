// Calls for clients and their saved ledgers (design of 2026-10-06). Paths go through the Next rewrite,
// like every other call in api.ts.
import { request, type Transaction, type TrialBalanceResult } from './api'

export type BusinessType = 'limited_company' | 'sole_trader' | 'partnership' | 'llp'

export interface ClientFields {
  name: string
  business_type: BusinessType
  contact_name: string       // the responsible person: the client's own contact
  contact_email: string
  contact_phone: string
  vat_registered: boolean
}

export interface Client extends ClientFields {
  id: number
  archived: boolean
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface ClientSummary extends Client {
  rows: number
  to_review: number          // rows with an error or a warning
}

export interface StatementCheck {
  status: 'ok' | 'gap' | 'none'
  difference: string | null
}

export interface Upload {
  id: number
  name: string               // the file's name, "Pasted text" or "Manual entry"
  kind: string
  sha256: string             // the file's fingerprint, to skip a file uploaded before
  model: string
  warnings: string[]
  created_at: string
  rows: number
  statement: StatementCheck | null
}

export type EditableField =
  'date' | 'description' | 'counterparty' | 'direction' | 'gross' | 'vat' | 'account_code' | 'document_type'

export interface SavedRow extends Transaction {
  id: number
  upload_id: number
  edited: boolean
  original: Partial<Record<EditableField, string | null>> | null   // what was read, once a person edits
}

export interface Ledger {
  client: Client
  uploads: Upload[]
  transactions: SavedRow[]
}

// A person's change to a row: Link or Include, an edit, or revert.
export type RowChange = Partial<Record<EditableField, string | null>> & {
  link?: string[] | null
  include?: boolean
  apart_from?: number[]
  revert?: boolean
}

export interface AccountChoice {
  code: string
  name: string
  type: string
  vat: string
}

const send = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const listClients = (archived = false) => request<ClientSummary[]>(`/api/clients?archived=${archived}`)
export const addClient = (fields: ClientFields) => request<Client>('/api/clients', send('POST', fields))
export const changeClient = (id: number, change: Partial<ClientFields> & { archived?: boolean }) =>
  request<Client>(`/api/clients/${id}`, send('PATCH', change))
export const getLedger = (id: number) => request<Ledger>(`/api/clients/${id}/ledger`)
export const changeRow = (id: number, rowId: number, change: RowChange) =>
  request<Ledger>(`/api/clients/${id}/rows/${rowId}`, send('PATCH', change))
export const addManualRows = (id: number, transactions: Transaction[]) =>
  request<Ledger>(`/api/clients/${id}/uploads`, send('POST', { name: 'Manual entry', kind: 'manual', transactions }))
export const removeRow = (id: number, rowId: number) =>
  request<Ledger>(`/api/clients/${id}/rows/${rowId}`, { method: 'DELETE' })
export const removeUpload = (id: number, uploadId: number) =>
  request<Ledger>(`/api/clients/${id}/uploads/${uploadId}`, { method: 'DELETE' })
export const clientTrialBalance = (id: number) => request<TrialBalanceResult>(`/api/clients/${id}/trial-balance`)
export const listAccounts = (businessType: BusinessType) =>
  request<AccountChoice[]>(`/api/accounts?business_type=${businessType}`)
export const exportUrl = (id: number) => `/api/clients/${id}/export.xlsx`
