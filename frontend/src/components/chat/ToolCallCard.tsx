import { useState } from 'react'
import { NavArrowDown, NavArrowRight, Check, Xmark } from 'iconoir-react'
import { Spinner } from '../ui/Spinner'
import { cn } from '../../lib/cn'
import type { ToolCall } from '../../api/types'

interface ToolCallCardProps {
  toolCall: ToolCall
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)

  const statusIcon = () => {
    switch (toolCall.status) {
      case 'running':
        return <Spinner size="sm" />
      case 'completed':
        return <Check className="w-4 h-4 text-green-400" />
      case 'failed':
        return <Xmark className="w-4 h-4 text-red-400" />
    }
  }

  return (
    <div className="my-2 rounded-lg border border-border bg-surface-tertiary/50 overflow-hidden">
      <button
        type="button"
        className="flex items-center gap-2 w-full px-3 py-2 text-left text-sm hover:bg-surface-tertiary transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <NavArrowDown className="w-3.5 h-3.5 text-text-secondary flex-shrink-0" />
        ) : (
          <NavArrowRight className="w-3.5 h-3.5 text-text-secondary flex-shrink-0" />
        )}
        <span className="flex-1 font-mono text-xs text-text-secondary truncate">
          {toolCall.name}
        </span>
        {statusIcon()}
      </button>

      {expanded && (
        <div className="px-3 pb-3 border-t border-border">
          {Object.keys(toolCall.input).length > 0 && (
            <div className="mt-2">
              <p className="text-xs text-text-secondary mb-1">Input</p>
              <pre
                className={cn(
                  'text-xs p-2 rounded bg-surface-primary overflow-x-auto',
                  'text-text-secondary font-mono whitespace-pre-wrap break-all'
                )}
              >
                {JSON.stringify(toolCall.input, null, 2)}
              </pre>
            </div>
          )}

          {toolCall.output && (
            <div className="mt-2">
              <p className="text-xs text-text-secondary mb-1">Output</p>
              <pre
                className={cn(
                  'text-xs p-2 rounded bg-surface-primary overflow-x-auto',
                  'text-text-secondary font-mono whitespace-pre-wrap break-all max-h-40'
                )}
              >
                {toolCall.output}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
