import { useEffect, useRef, useCallback, type RefObject } from 'react'
import type { Message } from '../../api/types'
import { MessageBubble } from './MessageBubble'
import { StreamingIndicator } from './StreamingIndicator'
import { Spinner } from '../ui/Spinner'

interface ToolActivity {
  name: string
  toolId: string
  status: 'running' | 'completed'
  startSeq: number
  endSeq?: number
}

interface MessageListProps {
  messages: Message[]
  streamingMessage: Message | null
  isStreaming: boolean
  bottomRef?: RefObject<HTMLDivElement | null>
  showToolCalls?: boolean
  tools?: ToolActivity[]
}

/** How close to the bottom (in px) counts as "at the bottom" */
const NEAR_BOTTOM_THRESHOLD = 100

export function MessageList({
  messages,
  streamingMessage,
  isStreaming,
  bottomRef: externalBottomRef,
  showToolCalls = false,
  tools = [],
}: MessageListProps) {
  const internalBottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const bottomRef = externalBottomRef || internalBottomRef

  // Track whether the user is near the bottom of the scroll container.
  // Starts true so the initial load scrolls to bottom.
  const isNearBottomRef = useRef(true)
  // Track previous message count to detect new messages (not streaming updates)
  const prevMessageCountRef = useRef(messages.length)

  const checkIfNearBottom = useCallback(() => {
    const el = containerRef.current
    if (!el) return true
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    return distanceFromBottom <= NEAR_BOTTOM_THRESHOLD
  }, [])

  const handleScroll = useCallback(() => {
    isNearBottomRef.current = checkIfNearBottom()
  }, [checkIfNearBottom])

  // When a NEW message arrives (messages array grows), always scroll to bottom.
  // This covers: user sends a message, streaming completes and message is added to history.
  useEffect(() => {
    if (messages.length > prevMessageCountRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      isNearBottomRef.current = true
    }
    prevMessageCountRef.current = messages.length
  }, [messages.length, bottomRef])

  // During streaming, only auto-scroll if the user is already near the bottom.
  // If the user scrolled up to read earlier messages, leave them alone.
  useEffect(() => {
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [streamingMessage?.content, streamingMessage?.tool_calls, bottomRef])

  const hasMessages = messages.length > 0 || streamingMessage

  // Compute running tools for the activity bar
  const runningTools = tools.filter((t) => t.status === 'running')

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto px-3 py-3 md:px-6 md:py-4 overscroll-contain"
      onScroll={handleScroll}
    >
      {!hasMessages && (
        <div className="flex items-center justify-center h-full">
          <div className="text-center">
            <h2 className="text-lg font-medium text-text-primary mb-2">
              Start a conversation
            </h2>
            <p className="text-sm text-text-secondary max-w-sm">
              Send a message to begin chatting with Claude Code.
            </p>
          </div>
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} showToolCalls={showToolCalls} />
      ))}

      {/* Activity bar during streaming -- shows running tools */}
      {isStreaming && runningTools.length > 0 && (
        <div className="flex items-center gap-2 px-3 py-2 mb-2 rounded-lg bg-surface-secondary border border-border">
          <Spinner size="sm" />
          <span className="text-xs font-medium text-text-primary">
            Running{' '}
            {runningTools.map((t) => t.name).join(', ')}
            ...
          </span>
        </div>
      )}

      {streamingMessage && !streamingMessage.is_complete && (
        <>
          <MessageBubble message={streamingMessage} showToolCalls={showToolCalls} />
          {isStreaming &&
            !streamingMessage.content &&
            (!streamingMessage.tool_calls ||
              streamingMessage.tool_calls.length === 0) && (
              <StreamingIndicator />
            )}
        </>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
