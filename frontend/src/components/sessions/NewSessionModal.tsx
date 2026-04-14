import { useState, useEffect, useRef } from 'react'
import {
  Xmark,
  ClipboardCheck,
  Code,
  EditPencil,
  Search,
  WarningTriangle,
  GraphUp,
  CheckCircle,
  DesignPencil,
  Globe,
  Gamepad,
  ServerConnection,
  NavArrowRight,
} from 'iconoir-react'
import { cn } from '../../lib/cn'
import { roles } from '../../data/roles'
import { useProjects, type Project } from '../../hooks/useProjects'
import { useProviders, useProviderModels } from '../../hooks/useProviders'
import { ProjectPicker } from './ProjectPicker'

interface NewSessionModalProps {
  isOpen: boolean
  onClose: () => void
  onCreate: (config: {
    title?: string
    role?: string
    projectName?: string
    projectDir?: string
    providerId?: string
    model?: string
  }) => void
}

const roleIconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  product: ClipboardCheck,
  coding: Code,
  writing: EditPencil,
  'deep-dive': Search,
  'bug-fixing': WarningTriangle,
  analysis: GraphUp,
  qa: CheckCircle,
  frontend: DesignPencil,
  'web-dev': Globe,
  'game-dev': Gamepad,
  nextjs: ServerConnection,
}

export function NewSessionModal({ isOpen, onClose, onCreate }: NewSessionModalProps) {
  const { projects, isLoading: projectsLoading } = useProjects()
  const { providers } = useProviders()
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [selectedRole, setSelectedRole] = useState<string | null>(null)
  const [sessionName, setSessionName] = useState('')
  const [userEditedName, setUserEditedName] = useState(false)
  const [isProjectPickerOpen, setIsProjectPickerOpen] = useState(false)
  const [selectedProviderId, setSelectedProviderId] = useState<string>('claude-code')
  const [selectedModel, setSelectedModel] = useState<string>('')
  const nameInputRef = useRef<HTMLInputElement>(null)

  const providerForModels = selectedProviderId === 'mlx-server' ? 'mlx-server' : null
  const { models: providerModels, isLoading: modelsLoading } = useProviderModels(providerForModels)

  useEffect(() => {
    if (isOpen) {
      setSelectedProject(null)
      setSelectedRole(null)
      setSessionName('')
      setUserEditedName(false)
      setIsProjectPickerOpen(false)
      setSelectedProviderId('claude-code')
      setSelectedModel('')
    }
  }, [isOpen])

  useEffect(() => {
    setSelectedModel('')
  }, [selectedProviderId])

  const handleProjectSelect = (project: Project) => {
    setSelectedProject(project)
    if (!userEditedName) {
      setSessionName(project.name)
    }
  }

  const handleProjectClear = () => {
    setSelectedProject(null)
    if (!userEditedName) setSessionName('')
  }

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSessionName(e.target.value)
    setUserEditedName(true)
  }

  const handleRoleToggle = (roleId: string) => {
    setSelectedRole(prev => (prev === roleId ? null : roleId))
  }

  const handleCreate = () => {
    onCreate({
      title: sessionName.trim() || undefined,
      role: selectedRole || undefined,
      projectName: selectedProject?.name || undefined,
      projectDir: selectedProject?.dir || undefined,
      providerId: selectedProviderId || undefined,
      model: selectedModel.trim() || undefined,
    })
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/60 backdrop-blur-sm">
      <div className="relative flex flex-col h-full max-w-lg mx-auto w-full bg-surface-primary">
        {/* Project picker overlay */}
        <ProjectPicker
          isOpen={isProjectPickerOpen}
          projects={projects}
          isLoading={projectsLoading}
          onSelect={handleProjectSelect}
          onClear={handleProjectClear}
          onClose={() => setIsProjectPickerOpen(false)}
        />

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] border-b border-border shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="p-2 -m-2 rounded-lg text-text-secondary active:bg-surface-tertiary transition-colors touch-manipulation"
            aria-label="Close"
          >
            <Xmark className="w-5 h-5" />
          </button>

          <span className="text-sm font-medium text-text-primary">New Session</span>

          {/* Spacer to center the title */}
          <div className="w-9" />
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-5 space-y-6">
          {/* Provider + Model */}
          <div className="space-y-2">
            <span className="block text-xs font-medium text-text-secondary uppercase tracking-wide">
              Provider
            </span>
            <div className="grid grid-cols-2 gap-2">
              {(providers.length > 0
                ? providers
                : [
                    { id: 'claude-code', name: 'Claude Code' },
                    { id: 'mlx-server', name: 'MLX Server' },
                  ]
              ).map((p) => {
                const active = selectedProviderId === p.id
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => setSelectedProviderId(p.id)}
                    className={cn(
                      'rounded-xl px-3 py-3 text-sm font-medium text-left transition-colors touch-manipulation',
                      active
                        ? 'bg-green-500/20 text-green-400 ring-2 ring-green-500/50'
                        : 'bg-surface-secondary border border-border text-text-primary active:bg-surface-tertiary'
                    )}
                  >
                    <div className="text-sm font-semibold">{p.name}</div>
                    <div className="text-xs text-text-secondary mt-0.5">
                      {p.id === 'claude-code' ? 'Claude CLI (cloud)' : 'Local MLX (Apple Silicon)'}
                    </div>
                  </button>
                )
              })}
            </div>
            {selectedProviderId === 'mlx-server' && (
              <div className="pt-1 space-y-1">
                <span className="block text-xs font-medium text-text-secondary">Model</span>
                {providerModels.length > 0 ? (
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    className={cn(
                      'w-full rounded-xl px-4 py-3 text-sm',
                      'bg-surface-secondary border border-border text-text-primary',
                      'focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30'
                    )}
                  >
                    <option value="">Default (first loaded)</option>
                    {providerModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                ) : (
                  <div className="rounded-xl bg-amber-500/10 border border-amber-500/20 px-3 py-2 text-xs text-amber-400">
                    {modelsLoading
                      ? 'Checking MLX Server...'
                      : 'No models loaded on the MLX Server. Start it and load a model, then try again.'}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Project Picker */}
          <div className="space-y-2">
            <span className="block text-xs font-medium text-text-secondary uppercase tracking-wide">
              Project (optional)
            </span>
            <button
              type="button"
              onClick={() => setIsProjectPickerOpen(true)}
              className={cn(
                'w-full rounded-xl px-4 py-3 text-sm text-left flex items-center',
                'bg-surface-secondary border border-border',
                'active:bg-surface-tertiary transition-colors touch-manipulation'
              )}
            >
              <span className={selectedProject ? 'text-text-primary' : 'text-text-secondary'}>
                {selectedProject ? selectedProject.name : 'Select a project'}
              </span>
              <NavArrowRight className="w-4 h-4 text-text-secondary ml-auto" />
            </button>
            {selectedProject && (
              <p className="text-xs text-text-secondary px-1">{selectedProject.dir}</p>
            )}
          </div>

          {/* Role Picker */}
          <div className="space-y-2">
            <span className="block text-xs font-medium text-text-secondary uppercase tracking-wide">
              Role (optional)
            </span>
            <div className="grid grid-cols-3 gap-2">
              {roles.map(role => {
                const Icon = roleIconMap[role.id]
                return (
                  <button
                    key={role.id}
                    type="button"
                    onClick={() => handleRoleToggle(role.id)}
                    className={cn(
                      'p-3 rounded-xl flex flex-col items-center gap-1.5 text-xs font-medium',
                      'touch-manipulation active:scale-95 transition-all',
                      selectedRole === role.id
                        ? 'bg-green-500/20 text-green-400 ring-2 ring-green-500/50 scale-105'
                        : cn(role.color, 'ring-1 ring-white/5')
                    )}
                  >
                    {Icon && <Icon className="w-5 h-5" />}
                    <span>{role.label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Session Name */}
          <div className="space-y-2">
            <label
              htmlFor="session-name"
              className="block text-xs font-medium text-text-secondary uppercase tracking-wide"
            >
              Session Name (optional)
            </label>
            <input
              ref={nameInputRef}
              id="session-name"
              type="text"
              value={sessionName}
              onChange={handleNameChange}
              placeholder="Session name"
              className={cn(
                'w-full rounded-xl px-4 py-3 text-base',
                'bg-surface-secondary border border-border text-text-primary',
                'placeholder:text-text-secondary',
                'focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30',
                'touch-manipulation'
              )}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-4 border-t border-border shrink-0">
          <button
            type="button"
            onClick={handleCreate}
            className={cn(
              'w-full py-3.5 rounded-xl text-sm font-semibold',
              'bg-green-500/20 text-green-400',
              'active:scale-[0.98] transition-all touch-manipulation',
              'ring-1 ring-green-500/30'
            )}
          >
            Start Session
          </button>
        </div>
      </div>
    </div>
  )
}
