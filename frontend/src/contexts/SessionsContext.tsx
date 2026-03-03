import { createContext, useContext, type ReactNode } from 'react'
import { useSessions } from '../hooks/useSessions'
import type { Session } from '../api/types'
import type { CreateSessionOptions } from '../api/client'

interface SessionsContextValue {
  sessions: Session[]
  isLoading: boolean
  error: string | null
  refresh: () => Promise<void>
  create: (options?: CreateSessionOptions) => Promise<Session>
  remove: (id: string) => Promise<void>
}

const SessionsContext = createContext<SessionsContextValue | null>(null)

export function SessionsProvider({ children }: { children: ReactNode }) {
  const value = useSessions()

  return (
    <SessionsContext.Provider value={value}>
      {children}
    </SessionsContext.Provider>
  )
}

export function useSessionsContext(): SessionsContextValue {
  const ctx = useContext(SessionsContext)
  if (!ctx) {
    throw new Error('useSessionsContext must be used within a SessionsProvider')
  }
  return ctx
}
