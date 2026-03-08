import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Spinner } from '../ui/Spinner'
import type { Message } from '../../api/types'
import { getMessages, sendMessage } from '../../api/client'
import { useSSE } from '../../hooks/useSSE'
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

  const { streamingMessage, isStreaming, error, agents } = useSSE(id)
  const prevIsStreaming = useRef(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

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
  // nothing was missed (e.g. reconnection gap).
  useEffect(() => {
    if (prevIsStreaming.current && !isStreaming && id) {
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
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [id])

  const handleSend = useCallback(
    async (content: string, images?: string[]) => {
      if (!id) return

      setSendError(null)

      try {
        await sendMessage(id, content, images)
        // Server persists the user message synchronously before spawning
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
        <ChatInput onSend={handleSend} disabled={inputDisabled} />
      </div>
      <div className="md:hidden">
        <MobileActionBar
          onSend={handleSend}
          onScrollToBottom={scrollToBottom}
          disabled={inputDisabled}
          lastAssistantMessage={lastAssistantMessage}
          isStreaming={isStreaming}
          streamingMessage={streamingMessage}
          agents={agents}
        />
      </div>
    </div>
  )
}
