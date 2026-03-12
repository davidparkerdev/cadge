import { useState, useEffect, useRef, useCallback } from 'react'
import { API_URL } from '../config'
import type { Message, ToolCall, StreamEvent, AgentInfo } from '../api/types'
import { log } from '../lib/logger'

interface UseSSEReturn {
  streamingMessage: Message | null
  isStreaming: boolean
  isConnected: boolean
  error: string | null
  clearError: () => void
  agents: AgentInfo[]
}

export function useSSE(sessionId: string | undefined): UseSSEReturn {
  const [streamingMessage, setStreamingMessage] = useState<Message | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const contentRef = useRef('')
  const thinkingRef = useRef('')
  const toolCallsRef = useRef<ToolCall[]>([])
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const agentsRef = useRef<AgentInfo[]>([])
  const currentToolNameRef = useRef<string>('')
  // Tracks whether we're between a `start` and `done`/`error` event.
  // Used to preserve streaming state across transport-level reconnections.
  const midStreamRef = useRef(false)
  // Incrementing this triggers the SSE effect to re-run, creating a new
  // EventSource. Used for reconnection after CLOSED state.
  const [reconnectTrigger, setReconnectTrigger] = useState(0)

  const clearError = useCallback(() => setError(null), [])

  useEffect(() => {
    if (!sessionId || sessionId === 'new') return

    let cleanedUp = false
    let reconnectTimer: number | undefined

    const url = `${API_URL}/api/sessions/${sessionId}/stream`
    log.info('sse', `Connecting to ${url}`)
    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      log.info('sse', `Connected: session=${sessionId}`)
      setError(null)
    }

    eventSource.onmessage = (event) => {
      try {
        const data: StreamEvent = JSON.parse(event.data)

        switch (data.type) {
          case 'ping':
            break

          case 'connected':
            setIsConnected(true)
            // If the backend reports active streaming and we're NOT already
            // mid-stream (i.e., this is a fresh join, not a reconnect),
            // initialize streaming state so the UI shows an indicator.
            // The replay buffer will deliver the actual content events next.
            //
            // If we ARE mid-stream (reconnecting after a transport drop),
            // skip initialization — we preserved contentRef/thinkingRef/etc.
            // across the reconnect, and the replayed `start` event will
            // properly reinitialize from the full replay buffer.
            if (data.streaming && !midStreamRef.current) {
              contentRef.current = ''
              thinkingRef.current = ''
              toolCallsRef.current = []
              setIsStreaming(true)
              setStreamingMessage({
                id: `streaming-${Date.now()}`,
                session_id: sessionId,
                role: 'assistant',
                content: '',
                tool_calls: [],
                thinking: '',
                is_complete: false,
                created_at: new Date().toISOString(),
              })
            }
            break

          case 'start':
          case 'message_start':
            // Start of assistant response — initialize streaming state.
            // This also fires on reconnect replay (server replays from `start`),
            // which correctly resets refs so the replay rebuilds content.
            midStreamRef.current = true
            contentRef.current = ''
            thinkingRef.current = ''
            toolCallsRef.current = []
            agentsRef.current = []
            setAgents([])
            setIsStreaming(true)
            setStreamingMessage({
              id: `streaming-${Date.now()}`,
              session_id: sessionId,
              role: 'assistant',
              content: '',
              tool_calls: [],
              thinking: '',
              is_complete: false,
              created_at: new Date().toISOString(),
            })
            break

          case 'content_block_start':
            if (data.content_block?.type === 'tool_use') {
              currentToolNameRef.current = data.content_block.name || 'unknown'
              toolCallsRef.current = [
                ...toolCallsRef.current,
                {
                  name: data.content_block.name || 'unknown',
                  input: {},
                  status: 'running',
                },
              ]
              setStreamingMessage((prev) =>
                prev
                  ? { ...prev, tool_calls: [...toolCallsRef.current] }
                  : null
              )
            }
            break

          case 'content_block_delta':
            if (data.delta?.type === 'text_delta' && data.delta.text) {
              contentRef.current += data.delta.text
              setStreamingMessage((prev) =>
                prev ? { ...prev, content: contentRef.current } : null
              )
            } else if (
              data.delta?.type === 'thinking_delta' &&
              data.delta.thinking
            ) {
              thinkingRef.current += data.delta.thinking
              setStreamingMessage((prev) =>
                prev ? { ...prev, thinking: thinkingRef.current } : null
              )
            } else if (
              data.delta?.type === 'input_json_delta' &&
              data.delta.partial_json
            ) {
              // Accumulate tool input JSON -- we just track that the tool is running
              // Full input will come from the completed message
            }
            break

          case 'content_block_stop':
            // Only mark non-Task tools as completed immediately.
            // Task (agent) tools remain "running" until agent_complete arrives.
            if (toolCallsRef.current.length > 0 && currentToolNameRef.current !== 'Task') {
              const lastIdx = toolCallsRef.current.length - 1
              const last = toolCallsRef.current[lastIdx]
              if (last.status === 'running') {
                toolCallsRef.current = toolCallsRef.current.map((tc, i) =>
                  i === lastIdx ? { ...tc, status: 'completed' } : tc
                )
                setStreamingMessage((prev) =>
                  prev
                    ? { ...prev, tool_calls: [...toolCallsRef.current] }
                    : null
                )
              }
            }
            currentToolNameRef.current = ''
            break

          case 'agent_spawn': {
            const newAgent: AgentInfo = {
              toolUseId: data.toolUseId || '',
              description: data.description || 'Sub-agent task',
              subagentType: data.subagentType || 'Task',
              prompt: data.prompt || '',
              status: 'running',
              startTime: Date.now(),
            }
            agentsRef.current = [...agentsRef.current, newAgent]
            setAgents([...agentsRef.current])
            break
          }

          case 'agent_complete': {
            const toolUseId = data.toolUseId
            agentsRef.current = agentsRef.current.map((a) =>
              a.toolUseId === toolUseId
                ? {
                    ...a,
                    status: (data.isError ? 'error' : 'completed') as AgentInfo['status'],
                    endTime: Date.now(),
                    result: data.result as string | undefined,
                    isError: data.isError as boolean | undefined,
                  }
                : a
            )
            setAgents([...agentsRef.current])
            break
          }

          case 'done':
          case 'message_stop':
            midStreamRef.current = false
            // Stream complete — finalize remaining running agents
            agentsRef.current = agentsRef.current.map((a) =>
              a.status === 'running' ? { ...a, status: 'completed' as const, endTime: Date.now() } : a
            )
            setAgents([...agentsRef.current])

            // Finalize the message
            if (contentRef.current) {
              setStreamingMessage((prev) =>
                prev
                  ? { ...prev, content: contentRef.current, is_complete: true }
                  : null
              )
            } else {
              setStreamingMessage((prev) =>
                prev ? { ...prev, is_complete: true } : null
              )
            }
            setIsStreaming(false)
            break

          case 'message_delta':
            // message_delta may carry final stop_reason, usage, etc.
            break

          case 'cancelled':
            midStreamRef.current = false
            setStreamingMessage(null)
            setIsStreaming(false)
            break

          case 'error':
            midStreamRef.current = false
            log.error('sse', `Stream error: ${data.error || 'unknown'}`, data)
            setError(data.error || 'An unknown error occurred')
            setIsStreaming(false)
            break
        }
      } catch (parseErr) {
        log.warn('sse', `Failed to parse SSE event`, parseErr)
      }
    }

    eventSource.onerror = () => {
      setIsConnected(false)
      if (eventSource.readyState === EventSource.CLOSED) {
        log.error('sse', `Connection closed: session=${sessionId}`)
        // Only clear streaming state if we're NOT mid-stream.
        // Mid-stream drops preserve the UI so content doesn't vanish.
        if (!midStreamRef.current) {
          setError('Stream connection lost — reconnecting...')
          setIsStreaming(false)
        }

        // Auto-reconnect: EventSource CLOSED state is permanent (no browser
        // retry). This commonly happens on iOS when the app backgrounds.
        // Create a new EventSource after a short delay.
        reconnectTimer = window.setTimeout(() => {
          if (!cleanedUp) {
            log.info('sse', `Reconnecting to session=${sessionId}`)
            setReconnectTrigger((n) => n + 1)
          }
        }, 2000)
      } else {
        log.warn('sse', `Connection error (will retry): session=${sessionId}`)
      }
    }

    // When the app returns from background (iOS PWA / Capacitor), the SSE
    // connection is likely dead. Re-establish it on visibility change.
    const handleVisibilityChange = () => {
      if (
        document.visibilityState === 'visible' &&
        eventSource.readyState === EventSource.CLOSED &&
        !cleanedUp
      ) {
        log.info('sse', `App foregrounded with dead SSE, reconnecting: session=${sessionId}`)
        setReconnectTrigger((n) => n + 1)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      cleanedUp = true
      log.info('sse', `Disconnecting: session=${sessionId}`)
      eventSource.close()
      eventSourceRef.current = null
      setIsConnected(false)

      if (midStreamRef.current) {
        // Mid-stream reconnect: preserve streamingMessage and refs so the
        // user doesn't see content vanish. The replayed `start` event from
        // the new connection will reset refs, and replayed content deltas
        // will rebuild the content quickly.
        log.info('sse', `Mid-stream disconnect, preserving streaming state`)
      } else {
        // Not mid-stream: clear stale streaming state on disconnect.
        // Without this, reconnecting after iOS background leaves
        // streamingMessage populated with partial content from the
        // previous connection, causing ghost messages.
        setStreamingMessage(null)
        setIsStreaming(false)
        contentRef.current = ''
        thinkingRef.current = ''
        toolCallsRef.current = []
        agentsRef.current = []
        setAgents([])
      }

      document.removeEventListener('visibilitychange', handleVisibilityChange)
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
  }, [sessionId, reconnectTrigger])

  return { streamingMessage, isStreaming, isConnected, error, clearError, agents }
}
