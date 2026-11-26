'use client'

import { useEffect, useState } from 'react'
import { useClientYear } from '@/components/ClientYearContext'
import { listAccounts, type AccountChoice } from '@/lib/clients'
import { accountList } from '@/lib/clientRules'

// The accounts a row can be coded to, for an issue that is fixed by choosing one; a bank account or card by the
// name the client gives it. Read once, and only when something asks for them (wanted).
export function useAccountChoices(wanted: boolean): AccountChoice[] {
  const { client } = useClientYear()
  const [accounts, setAccounts] = useState<AccountChoice[]>([])
  useEffect(() => {
    if (!wanted || accounts.length) return
    let current = true
    listAccounts(client.id).then(found => {
      if (!current) return
      const named = found.map(a => ({ ...a, name: client.bank_accounts.find(b => b.code === a.code)?.name || a.name }))
      setAccounts(accountList(named, { code: '', name: '' }, ''))
    }).catch(() => {})
    return () => { current = false }
  }, [wanted, accounts.length, client.id, client.bank_accounts])
  return accounts
}
