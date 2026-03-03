import { useNavigate, useParams } from 'react-router-dom'
import { ChatBubble, Trash } from 'iconoir-react'
import { cn } from '../../lib/cn'
import type { Session } from '../../api/types'

interface SessionItemProps {
  session: Session
  onDelete: (id: string) => void
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

export function SessionItem({ session, onDelete }: SessionItemProps) {
  const navigate = useNavigate()
  const { id: activeId } = useParams()
  const isActive = activeId === session.id

  return (
    <div
      className={cn(
        'group flex items-center gap-2 px-3 py-2.5 mx-2 rounded-lg cursor-pointer transition-colors',
        isActive
          ? 'bg-accent/10 text-accent'
          : 'text-text-secondary hover:text-text-primary hover:bg-surface-tertiary'
      )}
      onClick={() => navigate(`/session/${session.id}`)}
      data-nav-item
    >
      <ChatBubble className="w-4 h-4 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm truncate">
          {session.title || 'New Session'}
        </p>
        <p className="text-xs text-text-secondary truncate">
          {formatRelativeTime(session.updated_at)}
        </p>
      </div>
      <button
        type="button"
        className={cn(
          'p-2 -m-1 rounded text-text-secondary transition-all touch-manipulation',
          'md:opacity-0 md:group-hover:opacity-100',
          'hover:bg-surface-tertiary hover:text-red-400',
          'active:bg-surface-tertiary active:text-red-400'
        )}
        onClick={(e) => {
          e.stopPropagation()
          onDelete(session.id)
        }}
        aria-label="Delete session"
      >
        <Trash className="w-4 h-4" />
      </button>
    </div>
  )
}
