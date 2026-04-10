import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

type AppState = {
  documentId: string | null
  setDocumentId: (id: string | null) => void
  auditId: string | null
  setAuditId: (id: string | null) => void
}

const StateContext = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [auditId, setAuditId] = useState<string | null>(null)

  const value = useMemo(() => ({ documentId, setDocumentId, auditId, setAuditId }), [documentId, auditId])
  return <StateContext.Provider value={value}>{children}</StateContext.Provider>
}

export function useAppState() {
  const state = useContext(StateContext)
  if (!state) throw new Error('useAppState must be used inside AppStateProvider')
  return state
}
