import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  Layout,
  Sidebar,
  SidebarHeader,
  SidebarNav,
  SidebarFooter,
  useSidebar,
} from '../ui/Layout'
import { Menu, Plus, Settings as SettingsIcon } from 'iconoir-react'
import { cn } from '../../lib/cn'
import { SessionsProvider, useSessionsContext } from '../../contexts/SessionsContext'
import { SessionList } from '../sessions/SessionList'
import { NewSessionModal } from '../sessions/NewSessionModal'

export function AppLayout() {
  return (
    <SessionsProvider>
      <Layout className="!h-dvh">
        <Sidebar width="w-72">
          <SidebarHeader>
            <h1 className="text-lg font-semibold text-text-primary">Cadge</h1>
            <p className="text-xs text-text-secondary mt-0.5">AI Chat</p>
          </SidebarHeader>

          <SidebarNav className="p-0">
            <SessionList />
          </SidebarNav>

          <SidebarFooter>
            <SidebarSettingsLink />
          </SidebarFooter>
        </Sidebar>

        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <MobileHeader />
          <Outlet />
        </main>
      </Layout>
    </SessionsProvider>
  )
}

function SidebarSettingsLink() {
  const navigate = useNavigate()
  const location = useLocation()
  const isActive = location.pathname === '/settings'

  return (
    <button
      type="button"
      onClick={() => navigate('/settings')}
      className={cn(
        'flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm transition-colors touch-manipulation',
        isActive
          ? 'bg-accent/10 text-accent'
          : 'text-text-secondary hover:text-text-primary hover:bg-surface-tertiary'
      )}
    >
      <SettingsIcon className="w-4 h-4" />
      <span>Settings</span>
    </button>
  )
}

function MobileHeader() {
  const { toggle } = useSidebar()
  const navigate = useNavigate()
  const { create } = useSessionsContext()
  const [isNewSessionOpen, setIsNewSessionOpen] = useState(false)

  const handleCreate = async (config: {
    title?: string
    role?: string
    projectName?: string
    projectDir?: string
    providerId?: string
    model?: string
  }) => {
    try {
      const session = await create(config)
      setIsNewSessionOpen(false)
      navigate(`/session/${session.id}`)
    } catch {
      // Error handled by context
    }
  }

  return (
    <>
      <NewSessionModal
        isOpen={isNewSessionOpen}
        onClose={() => setIsNewSessionOpen(false)}
        onCreate={handleCreate}
      />
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-surface-secondary md:hidden">
        <span className="text-sm font-medium text-text-primary">Cadge</span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => navigate('/settings')}
            className="p-2.5 -m-1 rounded text-text-secondary hover:text-text-primary active:bg-surface-tertiary transition-colors touch-manipulation"
            aria-label="Settings"
          >
            <SettingsIcon className="w-4.5 h-4.5" />
          </button>
          <button
            type="button"
            onClick={() => setIsNewSessionOpen(true)}
            className="p-2.5 -m-1 rounded text-teal-400 hover:text-teal-300 active:bg-surface-tertiary transition-colors touch-manipulation"
            aria-label="New session"
          >
            <Plus className="w-5 h-5" />
          </button>
          <button
            type="button"
            onClick={toggle}
            className="p-2.5 -m-1 rounded text-text-secondary hover:text-text-primary active:bg-surface-tertiary transition-colors touch-manipulation"
            aria-label="Toggle navigation"
          >
            <Menu className="w-5 h-5" />
          </button>
        </div>
      </div>
    </>
  )
}
