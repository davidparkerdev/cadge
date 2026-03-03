import { useState } from 'react'
import { NavArrowDown, NavArrowRight } from 'iconoir-react'
import { cn } from '../../lib/cn'
import type { Message } from '../../api/types'
import { ToolCallCard } from './ToolCallCard'

interface MessageBubbleProps {
  message: Message
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false)
  const isUser = message.role === 'user'

  return (
    <div
      className={cn(
        'flex w-full mb-4',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      <div
        className={cn(
          'max-w-[90%] md:max-w-[70%] rounded-xl px-3.5 py-2.5 md:px-4 md:py-3',
          isUser
            ? 'bg-accent/15 text-text-primary border border-accent/20'
            : 'bg-surface-secondary text-text-primary border border-border'
        )}
      >
        {/* Thinking block (assistant only) */}
        {!isUser && message.thinking && (
          <div className="mb-2">
            <button
              type="button"
              className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-secondary transition-colors"
              onClick={() => setThinkingExpanded(!thinkingExpanded)}
            >
              {thinkingExpanded ? (
                <NavArrowDown className="w-3 h-3" />
              ) : (
                <NavArrowRight className="w-3 h-3" />
              )}
              Thinking
            </button>
            {thinkingExpanded && (
              <div className="mt-1 pl-4 border-l-2 border-accent/20 text-xs text-text-secondary whitespace-pre-wrap">
                {message.thinking}
              </div>
            )}
          </div>
        )}

        {/* Tool calls (assistant only, excluding Task agent calls) */}
        {!isUser &&
          Array.isArray(message.tool_calls) &&
          message.tool_calls.filter((tc) => tc.name !== 'Task').length > 0 && (
            <div className="mb-2">
              {message.tool_calls
                .filter((tc) => tc.name !== 'Task')
                .map((tc, i) => (
                  <ToolCallCard key={`${tc.name}-${i}`} toolCall={tc} />
                ))}
            </div>
          )}

        {/* Message content */}
        {message.content?.trim() && (
          <div className="text-sm whitespace-pre-wrap break-words leading-relaxed [overflow-wrap:anywhere]">
            {message.content.trim()}
          </div>
        )}
      </div>
    </div>
  )
}
