import { useState, useRef, useEffect } from 'react'
import { NavArrowLeft, Search } from 'iconoir-react'
import { cn } from '../../lib/cn'
import type { Project } from '../../hooks/useProjects'

interface ProjectPickerProps {
  isOpen: boolean
  projects: Project[]
  isLoading: boolean
  onSelect: (project: Project) => void
  onClear: () => void
  onClose: () => void
}

export function ProjectPicker({
  isOpen,
  projects,
  isLoading,
  onSelect,
  onClear,
  onClose,
}: ProjectPickerProps) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Reset search and focus input when opened
  useEffect(() => {
    if (isOpen) {
      setQuery('')
      // Small delay so the DOM is ready
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [isOpen])

  const filtered = query.trim()
    ? projects.filter((p) =>
        p.name.toLowerCase().includes(query.toLowerCase())
      )
    : projects

  if (!isOpen) return null

  return (
    <div className="absolute inset-0 z-10 flex flex-col bg-surface-primary">
      {/* Header with back + search */}
      <div className="shrink-0 border-b border-border">
        <div className="flex items-center gap-2 px-3 py-3 pt-[max(0.75rem,env(safe-area-inset-top))]">
          <button
            type="button"
            onClick={onClose}
            className="p-2 -m-1 rounded-lg text-text-secondary active:bg-surface-tertiary transition-colors touch-manipulation"
            aria-label="Back"
          >
            <NavArrowLeft className="w-5 h-5" />
          </button>
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-secondary pointer-events-none" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search projects..."
              className={cn(
                'w-full rounded-lg pl-9 pr-3 py-2.5 text-base',
                'bg-surface-secondary border border-border text-text-primary',
                'placeholder:text-text-secondary',
                'focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30',
                'touch-manipulation'
              )}
            />
          </div>
        </div>
      </div>

      {/* Project list */}
      <div className="flex-1 overflow-y-auto">
        {/* None / clear option */}
        <button
          type="button"
          onClick={() => {
            onClear()
            onClose()
          }}
          className="w-full text-left px-5 py-3.5 border-b border-border/50 text-sm text-text-secondary active:bg-surface-tertiary transition-colors touch-manipulation"
        >
          No project
        </button>

        {isLoading && (
          <p className="px-5 py-8 text-sm text-text-secondary text-center">Loading...</p>
        )}

        {!isLoading && filtered.length === 0 && (
          <p className="px-5 py-8 text-sm text-text-secondary text-center">
            {query ? 'No matches' : 'No projects found'}
          </p>
        )}

        {filtered.map((project) => (
          <button
            key={project.id}
            type="button"
            onClick={() => {
              onSelect(project)
              onClose()
            }}
            className="w-full text-left px-5 py-3.5 border-b border-border/50 active:bg-surface-tertiary transition-colors touch-manipulation"
          >
            <span className="block text-sm text-text-primary">{project.name}</span>
            <span className="block text-xs text-text-secondary mt-0.5 truncate">{project.dir}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
