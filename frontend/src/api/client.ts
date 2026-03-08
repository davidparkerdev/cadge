import { API_URL } from '../config'
import type { Session, Message } from './types'
import { log } from '../lib/logger'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const method = options?.method || 'GET'
  log.debug('api', `${method} ${path}`)

  const res = await fetch(`${API_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!res.ok) {
    const body = await res.text()
    const errMsg = `API error ${res.status}: ${body}`
    log.error('api', `${method} ${path} -> ${errMsg}`)
    throw new Error(errMsg)
  }

  // 204 No Content — nothing to parse
  if (res.status === 204) {
    return undefined as T
  }

  return res.json()
}

// Sessions

export async function listSessions(): Promise<Session[]> {
  return request<Session[]>('/api/sessions')
}

export async function getSession(id: string): Promise<Session> {
  return request<Session>(`/api/sessions/${id}`)
}

export interface CreateSessionOptions {
  title?: string
  role?: string
  projectName?: string
  projectDir?: string
}

export async function createSession(options?: CreateSessionOptions): Promise<Session> {
  const body: Record<string, unknown> = {}
  if (options?.title) body.title = options.title
  if (options?.role) body.role = options.role
  if (options?.projectName) body.project_name = options.projectName
  if (options?.projectDir) body.project_dir = options.projectDir
  return request<Session>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function deleteSession(id: string): Promise<void> {
  await request<void>(`/api/sessions/${id}`, { method: 'DELETE' })
}

// Messages

export async function getMessages(sessionId: string): Promise<Message[]> {
  return request<Message[]>(`/api/sessions/${sessionId}/messages`)
}

export async function sendMessage(
  sessionId: string,
  content: string,
  images?: string[]
): Promise<void> {
  const body: Record<string, unknown> = { content }
  if (images && images.length > 0) {
    body.images = images
  }
  await request<void>(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
