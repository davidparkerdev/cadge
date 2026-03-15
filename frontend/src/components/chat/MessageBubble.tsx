import { useState } from 'react'
import { NavArrowDown, NavArrowRight, WarningTriangle } from 'iconoir-react'
import { cn } from '../../lib/cn'
import type { Message } from '../../api/types'
import { ToolCallCard } from './ToolCallCard'

function toDataUri(src: string): string {
  if (src.startsWith('data:')) return src
  return `data:image/png;base64,${src}`
}

interface MessageBubbleProps {
  message: Message
  showToolCalls?: boolean
}

/** True when the message was saved from an interrupted or errored stream. */
function isInterrupted(message: Message): boolean {
  return (
    message.role === 'assistant' &&
    (message.status === 'incomplete' || message.status === 'error')
  )
}

export function MessageBubble({ message, showToolCalls = false }: MessageBubbleProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false)
  const [isExpanded, setIsExpanded] = useState(false)
  const [expandedImage, setExpandedImage] = useState<string | null>(null)
  const isUser = message.role === 'user'
  const interrupted = isInterrupted(message)

  // Show summary toggle when assistant message has both a summary and
  // substantial content (>300 chars)
  const hasSummary =
    !isUser &&
    !!message.summary &&
    !!message.content &&
    message.content.length > 300

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
            : interrupted
              ? 'bg-surface-secondary text-text-primary border border-amber-500/30'
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

        {/* Tool calls (assistant only, hidden by default — toggled via Tools button) */}
        {showToolCalls &&
          !isUser &&
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

        {isUser && message.images && message.images.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {message.images.map((img, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setExpandedImage(toDataUri(img))}
                className="block rounded-lg overflow-hidden border border-border/50 hover:border-accent/40 transition-colors"
              >
                <img
                  src={toDataUri(img)}
                  alt={`Attachment ${i + 1}`}
                  className="max-w-[200px] max-h-[150px] object-contain"
                />
              </button>
            ))}
          </div>
        )}

        {hasSummary && !isExpanded ? (
          <div className="text-sm whitespace-pre-wrap break-words leading-relaxed [overflow-wrap:anywhere]">
            {message.summary}
          </div>
        ) : (
          message.content?.trim() && (
            <div className="text-sm whitespace-pre-wrap break-words leading-relaxed [overflow-wrap:anywhere]">
              {message.content.trim()}
            </div>
          )
        )}

        {/* Summary toggle button */}
        {hasSummary && (
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="text-xs text-blue-400 hover:text-blue-300 mt-2 font-medium"
          >
            {isExpanded ? 'Show summary' : 'Show full response'}
          </button>
        )}

        {interrupted && (
          <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-400 font-medium">
            <WarningTriangle className="w-3.5 h-3.5 flex-shrink-0" />
            {message.status === 'error'
              ? 'Response encountered an error'
              : 'Response was interrupted'}
          </div>
        )}

      </div>

      {expandedImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
          onClick={() => setExpandedImage(null)}
          onKeyDown={(e) => { if (e.key === 'Escape') setExpandedImage(null) }}
          tabIndex={0}
          autoFocus
          role="dialog"
        >
          <img
            src={expandedImage}
            alt="Expanded attachment"
            className="max-w-full max-h-full object-contain rounded-lg"
          />
        </div>
      )}
    </div>
  )
}
