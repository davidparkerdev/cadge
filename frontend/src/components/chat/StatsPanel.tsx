import { useMemo } from 'react'
import { cn } from '../../lib/cn'
import type { StatsSnapshot } from '../../api/types'
import type { TokenSample } from '../../hooks/useEventStream'

interface StatsPanelProps {
  stats: StatsSnapshot | null
  samples: TokenSample[]
  isStreaming: boolean
}

function formatNumber(n?: number): string {
  if (n === undefined || n === null) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toFixed(0)
}

function formatSeconds(s?: number): string {
  if (s === undefined || s === null) return '—'
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rem = Math.round(s % 60)
  return `${m}m ${rem}s`
}

function Sparkline({ samples }: { samples: TokenSample[] }) {
  const path = useMemo(() => {
    if (samples.length < 2) return ''
    const values = samples.map(s => s.tokensPerSecond)
    const max = Math.max(1, ...values)
    const min = Math.min(0, ...values)
    const range = Math.max(0.001, max - min)
    const W = 100
    const H = 24
    return samples
      .map((s, i) => {
        const x = (i / (samples.length - 1)) * W
        const y = H - ((s.tokensPerSecond - min) / range) * H
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
      })
      .join(' ')
  }, [samples])

  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="w-full h-6">
      {path && (
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="text-green-400"
        />
      )}
    </svg>
  )
}

export function StatsPanel({ stats, samples, isStreaming }: StatsPanelProps) {
  if (!stats && !isStreaming) return null

  const contextUsed = stats?.contextUsed
  const contextMax = stats?.contextMax
  const contextPct = contextUsed && contextMax ? Math.min(100, (contextUsed / contextMax) * 100) : null

  return (
    <div className="mx-3 mb-2 rounded-xl border border-border bg-surface-secondary p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">Stats</span>
        {stats?.model && (
          <span className="text-xs text-text-secondary font-mono truncate ml-2 max-w-[60%]">
            {stats.model}
          </span>
        )}
      </div>

      {contextUsed !== undefined && (
        <div className="mb-3">
          <div className="flex items-baseline justify-between text-xs mb-1">
            <span className="text-text-secondary font-medium">Context</span>
            <span className="text-text-primary font-mono">
              {formatNumber(contextUsed)}{contextMax ? ` / ${formatNumber(contextMax)}` : ''}
            </span>
          </div>
          <div className="h-2 rounded-full bg-surface-tertiary overflow-hidden">
            <div
              className={cn(
                'h-full rounded-full transition-all',
                contextPct && contextPct > 85 ? 'bg-red-400' : contextPct && contextPct > 65 ? 'bg-amber-400' : 'bg-green-400'
              )}
              style={{ width: contextPct !== null ? `${contextPct}%` : '0%' }}
            />
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 text-sm">
        <StatCell label="Tokens in" value={formatNumber(stats?.tokensIn)} />
        <StatCell label="Tokens out" value={formatNumber(stats?.tokensOut)} />
        <StatCell label="Elapsed" value={formatSeconds(stats?.elapsedSeconds)} />
      </div>

      <div className="mt-3">
        <div className="flex items-baseline justify-between text-xs mb-1">
          <span className="text-text-secondary font-medium">Tokens / sec</span>
          <span className="text-text-primary font-mono">
            {stats?.tokensPerSecond !== undefined ? stats.tokensPerSecond.toFixed(1) : '—'}
          </span>
        </div>
        <Sparkline samples={samples} />
      </div>
    </div>
  )
}

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface-tertiary px-2 py-1.5">
      <div className="text-xs text-text-secondary font-medium">{label}</div>
      <div className="text-sm text-text-primary font-mono">{value}</div>
    </div>
  )
}
