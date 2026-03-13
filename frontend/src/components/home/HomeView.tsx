import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'iconoir-react'
import { cn } from '../../lib/cn'
import { useSessionsContext } from '../../contexts/SessionsContext'
import { SessionItem } from '../sessions/SessionItem'
import { NewSessionModal } from '../sessions/NewSessionModal'

export function HomeView() {
  const navigate = useNavigate()
  const { sessions, remove, create } = useSessionsContext()
  const [isNewSessionOpen, setIsNewSessionOpen] = useState(false)

  const handleDelete = async (id: string) => {
    try {
      await remove(id)
    } catch {
      // Error handled by context
    }
  }

  const handleCreate = async (config: {
    title?: string
    role?: string
    projectName?: string
    projectDir?: string
  }) => {
    try {
      const session = await create(config)
      setIsNewSessionOpen(false)
      navigate(`/session/${session.id}`)
    } catch {
      // Error handled by context
    }
  }

  // Recent sessions: show last 10
  const recentSessions = sessions.slice(0, 10)

  return (
    <div className="flex-1 flex flex-col items-center px-4 pt-6 pb-8 overflow-y-auto">
      <NewSessionModal
        isOpen={isNewSessionOpen}
        onClose={() => setIsNewSessionOpen(false)}
        onCreate={handleCreate}
      />

      <div className="w-full max-w-md space-y-6">
        {/* Subtitle */}
        <p className="text-sm text-text-secondary text-center">
          Select a session or create a new one
        </p>

        {/* New session button -- opens modal directly via React state,
            no CustomEvent needed since we have context access here */}
        <div className="md:hidden">
          <button
            type="button"
            onClick={() => setIsNewSessionOpen(true)}
            className={cn(
              'w-full py-4 rounded-xl text-sm font-semibold',
              'bg-teal-500/20 text-teal-400',
              'active:scale-[0.98] transition-all touch-manipulation',
              'ring-1 ring-teal-500/30',
              'flex items-center justify-center gap-2',
            )}
          >
            <Plus className="w-5 h-5" />
            New Session
          </button>
        </div>

        {/* Recent sessions */}
        {recentSessions.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-xs font-medium text-text-secondary uppercase tracking-wide px-1">
              Recent Sessions
            </h2>
            <div className="bg-surface-secondary rounded-xl border border-border overflow-hidden">
              {recentSessions.map((session) => (
                <SessionItem
                  key={session.id}
                  session={session}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
