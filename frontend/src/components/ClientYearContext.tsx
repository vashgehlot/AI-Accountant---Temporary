'use client'

import { createContext, useContext } from 'react'
import type { Client, Ledger, Year } from '@/lib/clients'
import type { ReadingFile } from '@/lib/clientRules'

// What every section of a client's year is given by the layout around it.
export interface ClientYear {
  client: Client
  year: Year
  years: Year[]
  ledger: Ledger             // the year's rows and uploads
  reload: () => Promise<void>   // fetches the year again, after a change
  show: (next: Ledger) => void  // shows the ledger a change was answered with, without fetching the year again
  error: string              // why the last load failed; '' when it worked
  reading: ReadingFile[]     // the files the API is reading for the client now, from any page or before a refresh
  checkReading: () => void   // looks again at once, after files were sent
}

export const ClientYearContext = createContext<ClientYear | null>(null)

export function useClientYear(): ClientYear {
  const value = useContext(ClientYearContext)
  if (!value) throw new Error('useClientYear is used inside a client year page.')
  return value
}
