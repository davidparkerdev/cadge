import { Brain, Terminal, ChatLines, PauseSolid } from 'iconoir-react'
import { cn } from '../../lib/cn'
import type { FocusSnapshot } from '../../api/types'

const KIND_ICON = {
  thinking: Brain,
  tool: Terminal,
  response: ChatLines,
  idle: PauseSolid,
} as const

const KIND_COLOR = {
  thinking: 'text-blue-300 bg-blue-500/10 border-blue-500/30',
  tool: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
  response: 'text-green-300 bg-green-500/10 border-green-500/30',
  idle: 'text-text-secondary bg-surface-tertiary border-border',
} as const

interface FocusIndicatorProps {
  focus: FocusSnapshot | null
  isStreaming: boolean
}

export function FocusIndicator({ focus, isStreaming }: FocusIndicatorProps) {
  if (!focus && !isStreaming) return null
  const kind: keyof typeof KIND_ICON = focus?.kind ?? 'thinking'
  const Icon = KIND_ICON[kind] ?? Brain
  const color = KIND_COLOR[kind] ?? KIND_COLOR.thinking
  const label = focus?.summary || (isStreaming ? 'Working' : 'Idle')

  return (
    <div
      className={cn(
        'mx-3 mb-2 flex items-center gap-2 px-3 py-2 rounded-xl border text-sm',
        color
      )}
      role="status"
      aria-live="polite"
    >
      <Icon className={cn('w-4 h-4 flex-shrink-0', isStreaming && 'animate-pulse')} />
      <span className="truncate font-medium">{label}</span>
      {focus?.detail && (
        <span className="ml-auto text-xs opacity-80 font-mono truncate max-w-[40%]">
          {focus.detail}
        </span>
      )}
    </div>
  )
}
