import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { getMe, setUnauthorizedHandler } from '../lib/api'
import type { AuthUser } from '../lib/types'

type AppState = {
  documentId: string | null
  setDocumentId: (id: string | null) => void
  auditId: string | null
  setAuditId: (id: string | null) => void
  selectedGroupId: string | null
  setSelectedGroupId: (id: string | null) => void
  authLoading: boolean
  token: string | null
  user: AuthUser | null
  signIn: (token: string, user: AuthUser) => void
  signOut: () => void
}

const StateContext = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [auditId, setAuditId] = useState<string | null>(null)
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authLoading, setAuthLoading] = useState(true)

  const signOut = useCallback(() => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    setToken(null)
    setUser(null)
    setDocumentId(null)
    setAuditId(null)
    setSelectedGroupId(null)
  }, [])

  const signIn = useCallback((nextToken: string, nextUser: AuthUser) => {
    localStorage.setItem('auth_token', nextToken)
    localStorage.setItem('auth_user', JSON.stringify(nextUser))
    setToken(nextToken)
    setUser(nextUser)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(signOut)
    const storedToken = localStorage.getItem('auth_token')
    if (!storedToken) {
      setAuthLoading(false)
      return
    }
    const storedUser = localStorage.getItem('auth_user')
    if (storedUser) {
      try {
        setUser(JSON.parse(storedUser) as AuthUser)
      } catch {
        // ignore malformed local cache
      }
    }
    setToken(storedToken)
    getMe(storedToken)
      .then((me) => {
        setUser(me)
        localStorage.setItem('auth_user', JSON.stringify(me))
      })
      .catch(() => {
        signOut()
      })
      .finally(() => setAuthLoading(false))
    return () => setUnauthorizedHandler(null)
  }, [signOut])

  const value = useMemo(
    () => ({
      documentId,
      setDocumentId,
      auditId,
      setAuditId,
      selectedGroupId,
      setSelectedGroupId,
      authLoading,
      token,
      user,
      signIn,
      signOut,
    }),
    [documentId, auditId, selectedGroupId, authLoading, token, user, signIn, signOut],
  )
  return <StateContext.Provider value={value}>{children}</StateContext.Provider>
}

export function useAppState() {
  const state = useContext(StateContext)
  if (!state) throw new Error('useAppState must be used inside AppStateProvider')
  return state
}
