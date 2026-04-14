import { useState, useEffect, useRef, useCallback } from 'react'
import { API_URL } from '../config'
import type { AgentInfo, FocusSnapshot, StatsSnapshot } from '../api/types'
import { log } from '../lib/logger'

interface ToolActivity {
  name: string
  toolId: string
  status: 'running' | 'completed'
  startSeq: number
  endSeq?: number
}

export interface TokenSample {
  t: number
  tokensPerSecond: number
}

interface UseEventStreamReturn {
  isStreaming: boolean
  isConnected: boolean
  error: string | null
  clearError: () => void
  tools: ToolActivity[]
  agents: AgentInfo[]
  streamingContent: string
  streamingThinking: string
  summary: string | null
  lastSeq: number
  focus: FocusSnapshot | null
  stats: StatsSnapshot | null
  tokenSamples: TokenSample[]
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
  const [focus, setFocus] = useState<FocusSnapshot | null>(null)
  const [stats, setStats] = useState<StatsSnapshot | null>(null)
  const [tokenSamples, setTokenSamples] = useState<TokenSample[]>([])

  const contentRef = useRef('')
  const thinkingRef = useRef('')
  const toolsRef = useRef<ToolActivity[]>([])
  const agentsRef = useRef<AgentInfo[]>([])
  const lastSeqRef = useRef(0)
  const eventSourceRef = useRef<EventSource | null>(null)
  const prevSessionIdRef = useRef<string | undefined>(undefined)
  const flushTimerRef = useRef<number | null>(null)

  const flushContent = useCallback(() => {
    setStreamingContent(contentRef.current)
    setStreamingThinking(thinkingRef.current)
    flushTimerRef.current = null
  }, [])

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current === null) {
      flushTimerRef.current = window.setTimeout(flushContent, 50)
    }
  }, [flushContent])

  const clearError = useCallback(() => setError(null), [])

  useEffect(() => {
    if (!sessionId || sessionId === 'new') return

    let cleanedUp = false
    let reconnectTimer: number | undefined
    let reconnectAttempts = 0
    const MAX_RECONNECT_ATTEMPTS = 10
    const BASE_DELAY_MS = 2000

    const isSessionChange = prevSessionIdRef.current !== sessionId
    prevSessionIdRef.current = sessionId

    if (isSessionChange) {
      contentRef.current = ''
      thinkingRef.current = ''
      toolsRef.current = []
      agentsRef.current = []
      setStreamingContent('')
      setStreamingThinking('')
      setTools([])
      setAgents([])
      setSummary(null)
      setIsStreaming(false)
      setLastSeq(0)
      setFocus(null)
      setStats(null)
      setTokenSamples([])
    }

    const connectSSE = (since: number) => {
      if (cleanedUp) return
      lastSeqRef.current = since
      const url = `${API_URL}/api/sessions/${sessionId}/events?since=${since}`
      log.info('events', `Connecting to ${url}`)
      const es = new EventSource(url)
      eventSourceRef.current = es

      es.onopen = () => {
        log.info('events', `Connected: session=${sessionId}`)
        setIsConnected(true)
        setError(null)
        reconnectAttempts = 0
      }

      es.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)

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
              setFocus(null)
              setStats(null)
              setTokenSamples([])
              break

            case 'focus_update': {
              const d = msg.data as Record<string, unknown>
              setFocus({
                summary: (d.summary as string) || '',
                kind: d.kind as FocusSnapshot['kind'],
                detail: d.detail as string | undefined,
                updatedAt: typeof d.updated_at === 'number' ? d.updated_at : Date.now() / 1000,
              })
              break
            }

            case 'stats_update': {
              const d = msg.data as Record<string, unknown>
              const snap: StatsSnapshot = {
                contextUsed: d.context_used as number | undefined,
                contextMax: d.context_max as number | undefined,
                tokensIn: d.tokens_in as number | undefined,
                tokensOut: d.tokens_out as number | undefined,
                tokensPerSecond: d.tokens_per_second as number | undefined,
                elapsedSeconds: d.elapsed_seconds as number | undefined,
                model: d.model as string | undefined,
              }
              setStats(snap)
              if (typeof snap.tokensPerSecond === 'number') {
                setTokenSamples(prev => {
                  const next = [...prev, { t: Date.now(), tokensPerSecond: snap.tokensPerSecond! }]
                  return next.length > 60 ? next.slice(next.length - 60) : next
                })
              }
              break
            }

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
              if (flushTimerRef.current !== null) {
                window.clearTimeout(flushTimerRef.current)
                flushTimerRef.current = null
              }
              setStreamingContent(contentRef.current)
              setStreamingThinking(thinkingRef.current)
              setSummary((d.summary as string) || null)
              setIsStreaming(false)
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

      es.onerror = () => {
        setIsConnected(false)
        if (es.readyState === EventSource.CLOSED) {
          reconnectAttempts++
          if (reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
            log.error(
              'events',
              `Connection failed after ${MAX_RECONNECT_ATTEMPTS} attempts, giving up: session=${sessionId}`
            )
            return
          }
          const delay = Math.min(
            BASE_DELAY_MS * Math.pow(2, reconnectAttempts - 1),
            30000
          )
          log.error(
            'events',
            `Connection closed: session=${sessionId}, attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}, retrying in ${delay}ms`
          )
          reconnectTimer = window.setTimeout(() => {
            if (!cleanedUp) {
              log.info('events', `Reconnecting with cursor=${lastSeqRef.current}`)
              connectSSE(lastSeqRef.current)
            }
          }, delay)
        }
      }
    }

    const handleVisibilityChange = () => {
      const es = eventSourceRef.current
      if (
        document.visibilityState === 'visible' &&
        (!es || es.readyState === EventSource.CLOSED) &&
        !cleanedUp
      ) {
        log.info('events', `App foregrounded, reconnecting with cursor=${lastSeqRef.current}`)
        connectSSE(lastSeqRef.current)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    if (isSessionChange) {
      fetch(`${API_URL}/api/sessions/${sessionId}/events/latest-seq`)
        .then(r => r.json())
        .then(data => {
          if (!cleanedUp) {
            connectSSE(data.seq || 0)
          }
        })
        .catch(() => {
          if (!cleanedUp) {
            connectSSE(lastSeqRef.current)
          }
        })
    } else {
      connectSSE(lastSeqRef.current)
    }

    return () => {
      cleanedUp = true
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      setIsConnected(false)
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current)
        flushTimerRef.current = null
      }
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
  }, [sessionId, scheduleFlush])

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
    focus,
    stats,
    tokenSamples,
  }
}
