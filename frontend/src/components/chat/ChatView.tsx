import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Spinner } from '../ui/Spinner'
import type { Message } from '../../api/types'
import { getMessages, sendMessage, cancelSession } from '../../api/client'
import { useEventStream } from '../../hooks/useEventStream'
import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'
import { MobileActionBar } from './MobileActionBar'
import { AgentStatusBar } from './AgentStatusBar'

export function ChatView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  const {
    isStreaming,
    isConnected: _isConnected,
    error,
    clearError: _clearError,
    tools,
    agents,
    streamingContent,
    streamingThinking,
    summary,
    lastSeq,
  } = useEventStream(id)

  const [isCancelling, setIsCancelling] = useState(false)
  const prevIsStreaming = useRef(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  // Build a streamingMessage from the event stream state for backward
  // compat with MessageList and MobileActionBar
  const streamingMessage: Message | null =
    isStreaming || streamingContent
      ? {
          id: `streaming-${lastSeq}`,
          session_id: id || '',
          role: 'assistant',
          content: streamingContent,
          thinking: streamingThinking,
          tool_calls: tools.map((t) => ({
            name: t.name,
            input: {},
            status: t.status,
          })),
          is_complete: !isStreaming,
          status: isStreaming ? 'streaming' : 'complete',
          created_at: new Date().toISOString(),
          summary: summary || undefined,
        }
      : null

  // Redirect to home if no valid session ID
  useEffect(() => {
    if (!id) {
      navigate('/', { replace: true })
    }
  }, [id, navigate])

  // Clear state and load message history when session changes
  useEffect(() => {
    setMessages([])

    if (!id) {
      setIsLoadingHistory(false)
      return
    }

    let cancelled = false
    setIsLoadingHistory(true)

    getMessages(id)
      .then((msgs) => {
        if (!cancelled) {
          // Filter out empty placeholder messages left by active or crashed streams.
          // These have status='streaming' with no content -- the real streamed content
          // comes via SSE. Non-empty streaming messages are kept (periodic saves).
          const filtered = msgs.filter(
            (m) => !(m.status === 'streaming' && !m.content?.trim())
          )
          setMessages(filtered)
        }
      })
      .catch(() => {
        // Session might not exist yet, that's OK
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingHistory(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [id])

  // When streaming ends via SSE, re-fetch messages from DB to ensure
  // nothing was missed (e.g. reconnection gap). Also clear cancelling state.
  useEffect(() => {
    if (prevIsStreaming.current && !isStreaming && id) {
      setIsCancelling(false)
      getMessages(id)
        .then((msgs) => {
          const filtered = msgs.filter(
            (m) => !(m.status === 'streaming' && !m.content?.trim())
          )
          setMessages(filtered)
        })
        .catch(() => {})
    }
    prevIsStreaming.current = isStreaming
  }, [isStreaming, id])

  const handleCancel = useCallback(async () => {
    if (!id || isCancelling) return
    setIsCancelling(true)
    try {
      await cancelSession(id)
      // The SSE stream will receive a 'cancelled' or 'done' event,
      // which sets isStreaming=false and triggers the effect above
      // to clear isCancelling.
    } catch {
      // If cancel API fails, reset cancelling state so user can retry
      setIsCancelling(false)
    }
  }, [id, isCancelling])

  // When the app returns from background (iOS PWA / Capacitor), refetch
  // messages so the user always sees the latest state. Without this, if
  // Claude responded while the app was backgrounded, the user sees stale
  // messages until they navigate away and back.
  useEffect(() => {
    if (!id) return

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        getMessages(id)
          .then((msgs) => {
            const filtered = msgs.filter(
              (m) => !(m.status === 'streaming' && !m.content?.trim())
            )
            setMessages(filtered)
          })
          .catch(() => {})
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () =>
      document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [id])

  const handleSend = useCallback(
    async (content: string, images?: string[]) => {
      if (!id) return

      setSendError(null)

      try {
        await sendMessage(id, content, images)
        // Server persists the user message synchronusly before spawning
        // Claude, so re-fetch to show the server-authoritative version.
        const msgs = await getMessages(id)
        const filtered = msgs.filter(
          (m) => !(m.status === 'streaming' && !m.content?.trim())
        )
        setMessages(filtered)
      } catch (err) {
        const errMsg =
          err instanceof Error ? err.message : 'Failed to send message'
        setSendError(errMsg)
      }
    },
    [id]
  )

  // Tool call visibility — toggled by the Tools button in MobileActionBar,
  // controls whether ToolCallCards render inline in MessageBubble.
  const [showToolCalls, setShowToolCalls] = useState(false)

  const inputDisabled = isStreaming

  // Find the last assistant message content for TTS playback
  const lastAssistantMessage = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant' && messages[i].content?.trim()) {
        return messages[i].content.trim()
      }
    }
    return undefined
  }, [messages])

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {isLoadingHistory ? (
        <div className="flex-1 flex items-center justify-center">
          <Spinner size="md" />
        </div>
      ) : (
        <MessageList
          messages={messages}
          streamingMessage={
            streamingMessage?.is_complete ? null : streamingMessage
          }
          isStreaming={isStreaming}
          bottomRef={bottomRef}
          showToolCalls={showToolCalls}
          tools={tools}
        />
      )}

      {agents.length > 0 && <AgentStatusBar agents={agents} />}

      {error && (
        <div className="px-4 py-2 text-center">
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}

      {sendError && (
        <div className="px-4 py-2 text-center">
          <p className="text-sm text-red-400">
            Failed to send message: {sendError}
          </p>
        </div>
      )}

      <div className="hidden md:block">
        <ChatInput
          onSend={handleSend}
          disabled={inputDisabled}
          isStreaming={isStreaming}
          isCancelling={isCancelling}
          onCancel={handleCancel}
        />
      </div>
      <div className="md:hidden">
        <MobileActionBar
          onSend={handleSend}
          onScrollToBottom={scrollToBottom}
          disabled={inputDisabled}
          lastAssistantMessage={lastAssistantMessage}
          isStreaming={isStreaming}
          isCancelling={isCancelling}
          onCancel={handleCancel}
          streamingMessage={streamingMessage}
          agents={agents}
          messages={messages}
          showTools={showToolCalls}
          onToggleTools={() => setShowToolCalls((v) => !v)}
        />
      </div>
    </div>
  )
}
