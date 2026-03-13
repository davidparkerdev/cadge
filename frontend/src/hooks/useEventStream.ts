import { useState, useEffect, useRef, useCallback } from 'react'
import { API_URL } from '../config'
import type { AgentInfo } from '../api/types'
import { log } from '../lib/logger'

interface ToolActivity {
  name: string
  toolId: string
  status: 'running' | 'completed'
  startSeq: number
  endSeq?: number
}

interface UseEventStreamReturn {
  // Derived state from events
  isStreaming: boolean
  isConnected: boolean
  error: string | null
  clearError: () => void

  // Activity feed (tools, agents) -- always available
  tools: ToolActivity[]
  agents: AgentInfo[]

  // Content -- accumulated from content_delta events
  streamingContent: string
  streamingThinking: string

  // Summary from stream_end event
  summary: string | null

  // Last sequence number (for cursor-based resume)
  lastSeq: number
}

export function useEventStream(
  sessionId: string | undefined
): UseEventStreamReturn {
  const [isStreaming, setIsStreaming] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tools, setTools] = useState<ToolActivity[]>([])
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingThinking, setStreamingThinking] = useState('')
  const [summary, setSummary] = useState<string | null>(null)
  const [lastSeq, setLastSeq] = useState(0)
  const [reconnectTrigger, setReconnectTrigger] = useState(0)

  // Refs for accumulation (avoid re-renders on every delta)
  const contentRef = useRef('')
  const thinkingRef = useRef('')
  const toolsRef = useRef<ToolActivity[]>([])
  const agentsRef = useRef<AgentInfo[]>([])
  const lastSeqRef = useRef(0)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Batch content updates -- instead of setState on every delta,
  // accumulate in ref and flush periodically
  const flushTimerRef = useRef<number | null>(null)

  const flushContent = useCallback(() => {
    setStreamingContent(contentRef.current)
    setStreamingThinking(thinkingRef.current)
    flushTimerRef.current = null
  }, [])

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current === null) {
      // Flush every 50ms -- fast enough to feel real-time,
      // slow enough to batch multiple deltas
      flushTimerRef.current = window.setTimeout(flushContent, 50)
    }
  }, [flushContent])

  const clearError = useCallback(() => setError(null), [])

  useEffect(() => {
    if (!sessionId || sessionId === 'new') return

    let cleanedUp = false
    let reconnectTimer: number | undefined

    // Connect with cursor -- resume from last known sequence
    const since = lastSeqRef.current
    const url = `${API_URL}/api/sessions/${sessionId}/events?since=${since}`
    log.info('events', `Connecting to ${url}`)
    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      log.info('events', `Connected: session=${sessionId}`)
      setIsConnected(true)
      setError(null)
    }

    eventSource.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)

        // Update cursor
        if (msg.seq) {
          lastSeqRef.current = msg.seq
          setLastSeq(msg.seq)
        }

        switch (msg.type) {
          case 'ping':
            break

          case 'connected':
            if (msg.streaming) {
              setIsStreaming(true)
            }
            break

          case 'stream_start':
            // Reset accumulators for new stream
            contentRef.current = ''
            thinkingRef.current = ''
            toolsRef.current = []
            agentsRef.current = []
            setStreamingContent('')
            setStreamingThinking('')
            setTools([])
            setAgents([])
            setSummary(null)
            setIsStreaming(true)
            break

          case 'content_delta': {
            const text =
              (msg.data as Record<string, unknown>)?.text as string || ''
            contentRef.current += text
            scheduleFlush()
            break
          }

          case 'thinking_delta': {
            const text =
              (msg.data as Record<string, unknown>)?.text as string || ''
            thinkingRef.current += text
            scheduleFlush()
            break
          }

          case 'tool_start': {
            const d = msg.data as Record<string, unknown>
            const tool: ToolActivity = {
              name: (d.tool_name as string) || 'unknown',
              toolId: (d.tool_id as string) || '',
              status: 'running',
              startSeq: msg.seq,
            }
            toolsRef.current = [...toolsRef.current, tool]
            setTools([...toolsRef.current])
            break
          }

          case 'tool_end': {
            const d = msg.data as Record<string, unknown>
            const toolId = d.tool_id as string
            toolsRef.current = toolsRef.current.map((t) =>
              t.toolId === toolId
                ? { ...t, status: 'completed' as const, endSeq: msg.seq }
                : t
            )
            setTools([...toolsRef.current])
            break
          }

          case 'agent_spawn': {
            const d = msg.data as Record<string, unknown>
            const agent: AgentInfo = {
              toolUseId: (d.tool_use_id as string) || '',
              description: (d.description as string) || 'Sub-agent task',
              subagentType: (d.subagent_type as string) || 'Task',
              prompt: '',
              status: 'running',
              startTime: Date.now(),
            }
            agentsRef.current = [...agentsRef.current, agent]
            setAgents([...agentsRef.current])
            break
          }

          case 'agent_complete': {
            const d = msg.data as Record<string, unknown>
            const toolUseId = d.tool_use_id as string
            agentsRef.current = agentsRef.current.map((a) =>
              a.toolUseId === toolUseId
                ? {
                    ...a,
                    status: (d.is_error ? 'error' : 'completed') as AgentInfo['status'],
                    endTime: Date.now(),
                    result: d.result as string,
                  }
                : a
            )
            setAgents([...agentsRef.current])
            break
          }

          case 'stream_end': {
            const d = msg.data as Record<string, unknown>
            // Flush any remaining content
            if (flushTimerRef.current !== null) {
              window.clearTimeout(flushTimerRef.current)
              flushTimerRef.current = null
            }
            setStreamingContent(contentRef.current)
            setStreamingThinking(thinkingRef.current)
            setSummary((d.summary as string) || null)
            setIsStreaming(false)
            // Mark any remaining running tools/agents as completed
            toolsRef.current = toolsRef.current.map((t) =>
              t.status === 'running'
                ? { ...t, status: 'completed' as const }
                : t
            )
            agentsRef.current = agentsRef.current.map((a) =>
              a.status === 'running'
                ? {
                    ...a,
                    status: 'completed' as const,
                    endTime: Date.now(),
                  }
                : a
            )
            setTools([...toolsRef.current])
            setAgents([...agentsRef.current])
            break
          }

          case 'stream_error': {
            const d = msg.data as Record<string, unknown>
            setError(
              (d.error as string) || 'An unknown error occurred'
            )
            setIsStreaming(false)
            break
          }

          case 'stream_cancelled':
            setIsStreaming(false)
            break
        }
      } catch (parseErr) {
        log.warn('events', 'Failed to parse event', parseErr)
      }
    }

    eventSource.onerror = () => {
      setIsConnected(false)
      if (eventSource.readyState === EventSource.CLOSED) {
        log.error('events', `Connection closed: session=${sessionId}`)
        // Auto-reconnect with cursor -- will resume from lastSeqRef.current
        reconnectTimer = window.setTimeout(() => {
          if (!cleanedUp) {
            log.info(
              'events',
              `Reconnecting with cursor=${lastSeqRef.current}`
            )
            setReconnectTrigger((n) => n + 1)
          }
        }, 2000)
      }
    }

    // Reconnect on app foregrounding
    const handleVisibilityChange = () => {
      if (
        document.visibilityState === 'visible' &&
        eventSource.readyState === EventSource.CLOSED &&
        !cleanedUp
      ) {
        log.info(
          'events',
          `App foregrounded, reconnecting with cursor=${lastSeqRef.current}`
        )
        setReconnectTrigger((n) => n + 1)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      cleanedUp = true
      eventSource.close()
      eventSourceRef.current = null
      setIsConnected(false)

      // Reset all content refs and state to prevent stale content
      // from previous session bleeding into the new session view
      contentRef.current = ''
      thinkingRef.current = ''
      toolsRef.current = []
      agentsRef.current = []
      lastSeqRef.current = 0
      setStreamingContent('')
      setStreamingThinking('')
      setTools([])
      setAgents([])
      setSummary(null)
      setIsStreaming(false)
      setLastSeq(0)

      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current)
        flushTimerRef.current = null
      }
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
  }, [sessionId, reconnectTrigger, scheduleFlush])

  return {
    isStreaming,
    isConnected,
    error,
    clearError,
    tools,
    agents,
    streamingContent,
    streamingThinking,
    summary,
    lastSeq,
  }
}
