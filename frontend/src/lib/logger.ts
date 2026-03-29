/**
 * Cadge Logger
 *
 * Structured logging for the frontend. All logs are:
 * 1. Written to the browser console with category prefix
 * 2. Buffered in memory (last 500 entries) for diagnostics
 * 3. Sent to the backend /api/logs endpoint for persistent storage
 *
 * Usage:
 *   import { log } from '../lib/logger'
 *   log.info('sse', 'Connected to session', { sessionId })
 *   log.error('image', 'Processing failed', error)
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

interface LogEntry {
  ts: string
  level: LogLevel
  category: string
  message: string
  data?: unknown
  error?: string
}

const BUFFER_SIZE = 500
const buffer: LogEntry[] = []

const API_URL =
  typeof window !== 'undefined'
    ? (() => {
        const host = window.location.hostname
        const port = host.endsWith('.ts.net') ? 43401 : 33401
        return `${window.location.protocol}//${host}:${port}`
      })()
    : ''

function formatError(err: unknown): string | undefined {
  if (!err) return undefined
  if (err instanceof Error) return `${err.name}: ${err.message}`
  return String(err)
}

function createEntry(
  level: LogLevel,
  category: string,
  message: string,
  data?: unknown
): LogEntry {
  const entry: LogEntry = {
    ts: new Date().toISOString(),
    level,
    category,
    message,
  }
  if (data instanceof Error) {
    entry.error = formatError(data)
  } else if (data !== undefined) {
    entry.data = data
  }
  return entry
}

function pushToBuffer(entry: LogEntry) {
  buffer.push(entry)
  if (buffer.length > BUFFER_SIZE) {
    buffer.shift()
  }
}

// Circuit breaker for backend logging
let _consecutiveFailures = 0
let _circuitOpen = false
let _circuitCooldown: number | null = null
const MAX_FAILURES = 3
const COOLDOWN_MS = 30_000 // 30 seconds

function sendToBackend(entry: LogEntry) {
  if (entry.level === 'debug') return
  if (_circuitOpen) return

  // Fire-and-forget -- don't block on logging
  try {
    fetch(`${API_URL}/api/logs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry),
    })
      .then(() => {
        // Success -- reset failure count
        _consecutiveFailures = 0
      })
      .catch(() => {
        _consecutiveFailures++
        if (_consecutiveFailures >= MAX_FAILURES) {
          _circuitOpen = true
          // Auto-reset after cooldown
          if (_circuitCooldown) clearTimeout(_circuitCooldown)
          _circuitCooldown = window.setTimeout(() => {
            _circuitOpen = false
            _consecutiveFailures = 0
            _circuitCooldown = null
          }, COOLDOWN_MS)
        }
      })
  } catch {
    // Silently fail
  }
}

function write(
  level: LogLevel,
  category: string,
  message: string,
  data?: unknown
) {
  const entry = createEntry(level, category, message, data)
  pushToBuffer(entry)

  const prefix = `[${category}]`
  const consoleFn =
    level === 'error'
      ? console.error
      : level === 'warn'
        ? console.warn
        : level === 'debug'
          ? console.debug
          : console.log

  if (data) {
    consoleFn(prefix, message, data)
  } else {
    consoleFn(prefix, message)
  }

  // Send warn/error to backend for persistent logging
  if (level === 'warn' || level === 'error') {
    sendToBackend(entry)
  }
}

export const log = {
  debug: (category: string, message: string, data?: unknown) =>
    write('debug', category, message, data),
  info: (category: string, message: string, data?: unknown) =>
    write('info', category, message, data),
  warn: (category: string, message: string, data?: unknown) =>
    write('warn', category, message, data),
  error: (category: string, message: string, data?: unknown) =>
    write('error', category, message, data),

  /** Get the in-memory log buffer for diagnostics */
  getBuffer: () => [...buffer],

  /** Get recent entries of a specific level or category */
  getRecent: (opts?: { level?: LogLevel; category?: string; limit?: number }) => {
    let entries = [...buffer]
    if (opts?.level) entries = entries.filter((e) => e.level === opts.level)
    if (opts?.category) entries = entries.filter((e) => e.category === opts.category)
    if (opts?.limit) entries = entries.slice(-opts.limit)
    return entries
  },
}

// Expose on window for debugging from console
if (typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).__cadge_log = log
}
