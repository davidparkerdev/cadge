import { useState, useEffect, useRef } from 'react'
import { NavArrowDown, NavArrowUp, Check, Xmark, Flash } from 'iconoir-react'
import { Spinner } from '../ui/Spinner'
import { cn } from '../../lib/cn'
import type { AgentInfo } from '../../api/types'

interface AgentStatusBarProps {
  agents: AgentInfo[]
}

export function AgentStatusBar({ agents }: AgentStatusBarProps) {
  const [expanded, setExpanded] = useState(false)

  if (agents.length === 0) return null

  const runningCount = agents.filter((a) => a.status === 'running').length
  const completedCount = agents.filter((a) => a.status === 'completed').length
  const errorCount = agents.filter((a) => a.status === 'error').length

  return (
    <div className="border-t border-border bg-surface-secondary">
      {/* Summary row */}
      <button
        type="button"
        className="flex items-center gap-2 w-full px-4 py-2.5 touch-manipulation"
        onClick={() => setExpanded(!expanded)}
      >
        <Flash className="w-4 h-4 text-accent flex-shrink-0" />
        <span className="text-sm font-medium text-text-primary">
          {agents.length} Agent{agents.length !== 1 ? 's' : ''}
        </span>
        <div className="flex items-center gap-3 flex-1 text-xs">
          {runningCount > 0 && (
            <span className="flex items-center gap-1.5 text-accent">
              <Spinner size="sm" />
              {runningCount} running
            </span>
          )}
          {completedCount > 0 && (
            <span className="flex items-center gap-1.5 text-green-400">
              <Check className="w-3.5 h-3.5" />
              {completedCount} done
            </span>
          )}
          {errorCount > 0 && (
            <span className="flex items-center gap-1.5 text-red-400">
              <Xmark className="w-3.5 h-3.5" />
              {errorCount} failed
            </span>
          )}
        </div>
        {expanded ? (
          <NavArrowUp className="w-4 h-4 text-text-secondary flex-shrink-0" />
        ) : (
          <NavArrowDown className="w-4 h-4 text-text-secondary flex-shrink-0" />
        )}
      </button>

      {/* Expanded detail list */}
      {expanded && (
        <div className="max-h-60 overflow-y-auto border-t border-border">
          {agents.map((agent) => (
            <AgentCard key={agent.toolUseId} agent={agent} />
          ))}
        </div>
      )}
    </div>
  )
}

function AgentCard({ agent }: { agent: AgentInfo }) {
  const [showResult, setShowResult] = useState(false)

  return (
    <div className="px-4 py-2.5 border-b border-border last:border-b-0">
      <div className="flex items-center gap-2">
        {agent.status === 'running' ? (
          <Spinner size="sm" />
        ) : agent.status === 'error' ? (
          <Xmark className="w-4 h-4 text-red-400 flex-shrink-0" />
        ) : (
          <Check className="w-4 h-4 text-green-400 flex-shrink-0" />
        )}
        <span className="flex-1 text-sm text-text-primary truncate">
          {agent.description}
        </span>
        <AgentTimer agent={agent} />
      </div>
      <div className="mt-1 ml-6">
        <span className="text-xs text-text-secondary">
          {agent.subagentType} agent
        </span>
      </div>
      {agent.status !== 'running' && agent.result && (
        <div className="mt-1.5 ml-6">
          <button
            type="button"
            onClick={() => setShowResult(!showResult)}
            className="text-xs text-accent touch-manipulation"
          >
            {showResult ? 'Hide result' : 'Show result'}
          </button>
          {showResult && (
            <p className="mt-1 text-xs text-text-secondary bg-surface-tertiary rounded px-2 py-1.5 whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
              {agent.result}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function AgentTimer({ agent }: { agent: AgentInfo }) {
  const [elapsed, setElapsed] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined)

  useEffect(() => {
    if (agent.status === 'running') {
      const update = () => setElapsed(Math.floor((Date.now() - agent.startTime) / 1000))
      update()
      intervalRef.current = setInterval(update, 1000)
      return () => clearInterval(intervalRef.current)
    }
    if (agent.endTime) {
      setElapsed(Math.floor((agent.endTime - agent.startTime) / 1000))
    }
  }, [agent.status, agent.startTime, agent.endTime])

  function fmt(s: number): string {
    if (s < 60) return `${s}s`
    return `${Math.floor(s / 60)}m ${s % 60}s`
  }

  return (
    <span className={cn(
      'text-xs font-mono flex-shrink-0',
      agent.status === 'running' ? 'text-accent' : 'text-text-secondary'
    )}>
      {fmt(elapsed)}
    </span>
  )
}
