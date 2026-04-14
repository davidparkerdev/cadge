import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CloudSync,
  Cpu,
  RefreshDouble,
  CheckCircle,
  WarningTriangle,
  NavArrowLeft,
} from 'iconoir-react'
import { cn } from '../../lib/cn'
import { listProviders, getProviderStatus, getProviderModels, getSettings, updateSetting } from '../../api/client'
import type { ProviderInfo, ProviderStatus, ProviderModel } from '../../api/types'
import { Spinner } from '../ui/Spinner'

const providerIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  'claude-code': CloudSync,
  'mlx-server': Cpu,
}

interface FeatureConfig {
  key: string
  label: string
  description: string
}

const FEATURES: FeatureConfig[] = [
  {
    key: 'summary',
    label: 'Summaries',
    description: 'AI-generated summary of what happened after each response',
  },
]

const SUMMARY_PROVIDERS = [
  { id: '', label: 'Disabled (deterministic fallback)' },
  { id: 'mlx-server', label: 'MLX Server (local)' },
  { id: 'anthropic', label: 'Anthropic API' },
]

function StatusBadge({ status }: { status: ProviderStatus | null; }) {
  if (!status) return <Spinner size="sm" />
  const isOk = status.status === 'available'
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium',
      isOk ? 'bg-green-500/15 text-green-400' : 'bg-zinc-500/15 text-zinc-400'
    )}>
      {isOk ? <CheckCircle className="w-3.5 h-3.5" /> : <WarningTriangle className="w-3.5 h-3.5" />}
      {isOk ? 'Connected' : 'Offline'}
    </span>
  )
}

export function SettingsView() {
  const navigate = useNavigate()
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [statuses, setStatuses] = useState<Record<string, ProviderStatus | null>>({})
  const [models, setModels] = useState<Record<string, ProviderModel[]>>({})
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState<string | null>(null)

  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const [savingKey, setSavingKey] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [providerList, settingsData] = await Promise.all([
        listProviders(),
        getSettings(),
      ])
      setProviders(providerList)
      setSettings(settingsData)

      const statusPromises = providerList.map(async (p) => {
        try {
          const s = await getProviderStatus(p.id)
          return [p.id, s] as const
        } catch {
          return [p.id, { status: 'error' as const, detail: 'Failed to check' }] as const
        }
      })
      const statusResults = await Promise.all(statusPromises)
      setStatuses(Object.fromEntries(statusResults))

      const modelPromises = providerList.map(async (p) => {
        try {
          const m = await getProviderModels(p.id)
          return [p.id, m] as const
        } catch {
          return [p.id, []] as const
        }
      })
      const modelResults = await Promise.all(modelPromises)
      setModels(Object.fromEntries(modelResults))
    } catch {
      setProviders([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const refreshProvider = async (providerId: string) => {
    setRefreshing(providerId)
    try {
      const [s, m] = await Promise.all([
        getProviderStatus(providerId),
        getProviderModels(providerId),
      ])
      setStatuses(prev => ({ ...prev, [providerId]: s }))
      setModels(prev => ({ ...prev, [providerId]: m }))
    } catch {
      // keep existing
    } finally {
      setRefreshing(null)
    }
  }

  const handleSettingChange = async (key: string, value: unknown) => {
    setSavingKey(key)
    try {
      await updateSetting(key, value)
      setSettings(prev => ({ ...prev, [key]: value }))
    } catch {
      // revert on failure
    } finally {
      setSavingKey(null)
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-4 py-6 space-y-8">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="p-2 -m-2 rounded-lg text-text-secondary hover:text-text-primary active:bg-surface-tertiary transition-colors touch-manipulation md:hidden"
            aria-label="Back"
          >
            <NavArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Settings</h1>
            <p className="text-sm text-text-secondary mt-0.5">Manage providers and configuration</p>
          </div>
        </div>

        <section className="space-y-4">
          <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">Feature Providers</h2>
          <p className="text-sm text-text-secondary">
            Choose which AI provider powers each feature. Chat provider is set per-session.
          </p>

          <div className="space-y-3">
            {FEATURES.map(feature => {
              const providerKey = `${feature.key}.provider_id`
              const modelKey = `${feature.key}.model`
              const currentProvider = (settings[providerKey] as string) || ''
              const currentModel = (settings[modelKey] as string) || ''

              const availableModels = currentProvider === 'mlx-server'
                ? models['mlx-server'] || []
                : []

              return (
                <div
                  key={feature.key}
                  className="rounded-xl bg-surface-secondary border border-border p-4 space-y-4"
                >
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">{feature.label}</h3>
                    <p className="text-xs text-text-secondary mt-0.5">{feature.description}</p>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-text-secondary mb-1.5">Provider</label>
                      <select
                        value={currentProvider}
                        onChange={(e) => handleSettingChange(providerKey, e.target.value)}
                        disabled={savingKey === providerKey}
                        className="w-full rounded-lg bg-surface-tertiary border border-border px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
                      >
                        {SUMMARY_PROVIDERS.map(p => (
                          <option key={p.id} value={p.id}>{p.label}</option>
                        ))}
                      </select>
                    </div>

                    {currentProvider === 'mlx-server' && (
                      <div>
                        <label className="block text-xs font-medium text-text-secondary mb-1.5">Model</label>
                        {availableModels.length > 0 ? (
                          <select
                            value={currentModel}
                            onChange={(e) => handleSettingChange(modelKey, e.target.value)}
                            disabled={savingKey === modelKey}
                            className="w-full rounded-lg bg-surface-tertiary border border-border px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
                          >
                            <option value="">Default (loaded model)</option>
                            {availableModels.map(m => (
                              <option key={m.id} value={m.id}>{m.name}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            type="text"
                            value={currentModel}
                            onChange={(e) => handleSettingChange(modelKey, e.target.value)}
                            placeholder="Leave blank for loaded model"
                            className="w-full rounded-lg bg-surface-tertiary border border-border px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent"
                          />
                        )}
                      </div>
                    )}

                    {currentProvider === 'anthropic' && (
                      <div>
                        <label className="block text-xs font-medium text-text-secondary mb-1.5">Model</label>
                        <select
                          value={currentModel}
                          onChange={(e) => handleSettingChange(modelKey, e.target.value)}
                          disabled={savingKey === modelKey}
                          className="w-full rounded-lg bg-surface-tertiary border border-border px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
                        >
                          <option value="">Haiku 4.5 (default)</option>
                          <option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
                          <option value="claude-sonnet-4-20250514">Sonnet 4</option>
                        </select>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">Providers</h2>
            <button
              type="button"
              onClick={fetchAll}
              className="text-xs text-text-secondary hover:text-text-primary transition-colors touch-manipulation flex items-center gap-1"
            >
              <RefreshDouble className="w-3.5 h-3.5" />
              Refresh all
            </button>
          </div>

          <div className="space-y-3">
            {providers.map(provider => {
              const Icon = providerIcons[provider.id] || Cpu
              const status = statuses[provider.id]
              const providerModels = models[provider.id] || []
              const isRefreshing = refreshing === provider.id

              return (
                <div
                  key={provider.id}
                  className="rounded-xl bg-surface-secondary border border-border p-4 space-y-4"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className="p-2.5 rounded-lg bg-surface-tertiary">
                        <Icon className="w-5 h-5 text-text-primary" />
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-text-primary">{provider.name}</h3>
                        <p className="text-xs text-text-secondary mt-0.5">{provider.description}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={status} />
                      <button
                        type="button"
                        onClick={() => refreshProvider(provider.id)}
                        className="p-1.5 rounded text-text-secondary hover:text-text-primary transition-colors touch-manipulation"
                        aria-label="Refresh status"
                      >
                        <RefreshDouble className={cn('w-4 h-4', isRefreshing && 'animate-spin')} />
                      </button>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {provider.supports_tools && <CapBadge label="Tool Use" />}
                    {provider.supports_thinking && <CapBadge label="Thinking" />}
                    {provider.supports_images && <CapBadge label="Images" />}
                    {provider.supports_agents && <CapBadge label="Agents" />}
                    {!provider.supports_tools && !provider.supports_thinking && (
                      <CapBadge label="Text Only" />
                    )}
                  </div>

                  {status && (
                    <div className="text-xs text-text-secondary space-y-1">
                      {status.version && (
                        <p>Version: <span className="text-text-primary">{status.version}</span></p>
                      )}
                      {status.base_url && (
                        <p>Endpoint: <span className="text-text-primary font-mono">{status.base_url}</span></p>
                      )}
                      {status.status === 'unavailable' && status.detail && (
                        <p className="text-amber-400">{status.detail}</p>
                      )}
                    </div>
                  )}

                  {providerModels.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-text-secondary uppercase tracking-wide">
                        Available Models ({providerModels.length})
                      </p>
                      <div className="space-y-1 max-h-48 overflow-y-auto">
                        {providerModels.map(model => (
                          <div
                            key={model.id}
                            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-tertiary"
                          >
                            <Cpu className="w-3.5 h-3.5 text-text-secondary flex-shrink-0" />
                            <span className="text-sm text-text-primary truncate">{model.name}</span>
                            {model.context_length && (
                              <span className="ml-auto text-xs text-text-secondary flex-shrink-0">
                                {Math.round(model.context_length / 1024)}k ctx
                              </span>
                            )}
                            {model.owned_by && (
                              <span className="text-xs text-text-secondary flex-shrink-0">
                                {model.owned_by}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {provider.id === 'mlx-server' && status?.status === 'unavailable' && (
                    <div className="rounded-lg bg-amber-500/10 border border-amber-500/20 p-3 space-y-2">
                      <p className="text-xs font-medium text-amber-400">MLX Server Not Running</p>
                      <ol className="text-xs text-text-secondary space-y-1 list-decimal list-inside">
                        <li>Start it: <span className="font-mono text-text-primary">thelab start mlx-server</span></li>
                        <li>Confirm it's up at <span className="font-mono text-text-primary">http://localhost:33339/v1/models</span></li>
                        <li>Load a model via the MLX Server UI or <span className="font-mono text-text-primary">POST /v1/models/load</span></li>
                        <li>Come back here and hit Refresh</li>
                      </ol>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">How It Works</h2>
          <div className="rounded-xl bg-surface-secondary border border-border p-4 space-y-3 text-sm text-text-secondary">
            <p>
              Each session is tied to a provider. When you create a new session, pick your provider and model at the top of the dialog.
            </p>
            <p>
              <span className="text-text-primary font-medium">Claude Code</span> sessions use the full Claude Code CLI with tool use, thinking, file editing, and agent spawning. Best for coding tasks.
            </p>
            <p>
              <span className="text-text-primary font-medium">MLX Server</span> sessions run entirely on your Apple Silicon machine. No data leaves your network. Supports the full tool suite (read_file, bash, grep, write_file, ls, glob) for agentic work.
            </p>
          </div>
        </section>
      </div>
    </div>
  )
}

function CapBadge({ label }: { label: string }) {
  return (
    <span className="px-2 py-0.5 rounded text-xs bg-surface-tertiary text-text-secondary">
      {label}
    </span>
  )
}
