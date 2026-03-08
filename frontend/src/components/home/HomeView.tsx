import { Plus } from 'iconoir-react'
import { cn } from '../../lib/cn'
import { useSessionsContext } from '../../contexts/SessionsContext'
import { SessionItem } from '../sessions/SessionItem'

export function HomeView() {
  const { sessions, remove } = useSessionsContext()

  const handleDelete = async (id: string) => {
    try {
      await remove(id)
    } catch {
      // Error handled by context
    }
  }

  // Recent sessions: show last 10
  const recentSessions = sessions.slice(0, 10)

  return (
    <div className="flex-1 flex flex-col items-center px-4 pt-6 pb-8 overflow-y-auto">
      <div className="w-full max-w-md space-y-6">
        {/* Subtitle */}
        <p className="text-sm text-text-secondary text-center">
          Select a session or create a new one
        </p>

        {/* New session button -- triggers the modal via MobileHeader's + button on mobile,
            or the sidebar New Session button on desktop. On mobile we provide a direct
            action here since the sidebar isn't visible. */}
        <div className="md:hidden">
          <button
            type="button"
            onClick={() => {
              // Dispatch a custom event that MobileHeader listens for
              window.dispatchEvent(new CustomEvent('stargate:new-session'))
            }}
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
