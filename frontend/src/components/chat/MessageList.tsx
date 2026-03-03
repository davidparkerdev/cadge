import { useEffect, useRef, type RefObject } from 'react'
import type { Message } from '../../api/types'
import { MessageBubble } from './MessageBubble'
import { StreamingIndicator } from './StreamingIndicator'

interface MessageListProps {
  messages: Message[]
  streamingMessage: Message | null
  isStreaming: boolean
  bottomRef?: RefObject<HTMLDivElement | null>
}

export function MessageList({
  messages,
  streamingMessage,
  isStreaming,
  bottomRef: externalBottomRef,
}: MessageListProps) {
  const internalBottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const bottomRef = externalBottomRef || internalBottomRef

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingMessage?.content, streamingMessage?.tool_calls, bottomRef])

  const hasMessages = messages.length > 0 || streamingMessage

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto px-3 py-3 md:px-6 md:py-4 overscroll-contain"
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
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {streamingMessage && !streamingMessage.is_complete && (
        <>
          <MessageBubble message={streamingMessage} />
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
