import { useState, useEffect, useCallback } from 'react'
import type { Session } from '../api/types'
import { listSessions, createSession, deleteSession } from '../api/client'
import type { CreateSessionOptions } from '../api/client'

interface UseSessionsReturn {
  sessions: Session[]
  isLoading: boolean
  error: string | null
  refresh: () => Promise<void>
  create: (options?: CreateSessionOptions) => Promise<Session>
  remove: (id: string) => Promise<void>
}

export function useSessions(): UseSessionsReturn {
  const [sessions, setSessions] = useState<Session[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setError(null)
      const data = await listSessions()
      setSessions(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sessions')
    } finally {
      setIsLoading(false)
    }
  }, [])

  const create = useCallback(
    async (options?: CreateSessionOptions) => {
      const session = await createSession(options)
      await refresh()
      return session
    },
    [refresh]
  )

  const remove = useCallback(
    async (id: string) => {
      await deleteSession(id)
      await refresh()
    },
    [refresh]
  )

  useEffect(() => {
    refresh()
  }, [refresh])

  return { sessions, isLoading, error, refresh, create, remove }
}
