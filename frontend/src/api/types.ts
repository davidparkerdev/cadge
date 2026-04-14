export interface Session {
  id: string
  title: string
  claude_session_id: string
  status: 'active' | 'archived'
  created_at: string
  updated_at: string
}

export type MessageStatus = 'complete' | 'streaming' | 'incomplete' | 'error'

export interface Message {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  tool_calls?: ToolCall[]
  thinking?: string
  images?: string[]
  is_complete: boolean
  status?: MessageStatus
  created_at: string
  summary?: string
}

export interface ToolCall {
  name: string
  input: Record<string, unknown>
  status: 'running' | 'completed' | 'failed'
  output?: string
}

export interface AgentInfo {
  toolUseId: string
  description: string
  subagentType: string
  prompt: string
  status: 'running' | 'completed' | 'error'
  startTime: number
  endTime?: number
  result?: string
  isError?: boolean
}

export interface ProviderInfo {
  id: string
  name: string
  description: string
  supports_tools: boolean
  supports_thinking: boolean
  supports_images: boolean
  supports_agents: boolean
  requires_api_key: boolean
  default_model?: string | null
  config?: Record<string, unknown>
}

export interface ProviderModel {
  id: string
  name: string
  context_length?: number | null
  owned_by?: string | null
}

export interface ProviderStatus {
  status: 'available' | 'unavailable' | 'error'
  detail?: string
  version?: string
  base_url?: string
  model_count?: number
}

export interface FocusSnapshot {
  summary: string
  kind?: 'thinking' | 'tool' | 'response' | 'idle'
  detail?: string
  updatedAt?: number
}

export interface StatsSnapshot {
  contextUsed?: number
  contextMax?: number
  tokensIn?: number
  tokensOut?: number
  tokensPerSecond?: number
  elapsedSeconds?: number
  model?: string
}

export type StreamEvent = {
  type:
    | 'start'
    | 'done'
    | 'connected'
    | 'message_start'
    | 'message_delta'
    | 'message_stop'
    | 'content_block_start'
    | 'content_block_delta'
    | 'content_block_stop'
    | 'error'
    | 'cancelled'
    | 'ping'
    | 'agent_spawn'
    | 'agent_complete'
    | 'focus_update'
    | 'stats_update'
  subtype?: string
  streaming?: boolean
  session_id?: string
  exit_code?: number
  content_block?: {
    type: string
    name?: string
    id?: string
  }
  delta?: {
    type: string
    text?: string
    thinking?: string
    partial_json?: string
  }
  index?: number
  message?: Message
  error?: string
  toolUseId?: string
  description?: string
  subagentType?: string
  prompt?: string
  result?: string
  isError?: boolean
  [key: string]: unknown
}
