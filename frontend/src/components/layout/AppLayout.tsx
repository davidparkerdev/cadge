import { useState, useEffect } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import {
  Layout,
  Sidebar,
  SidebarHeader,
  SidebarNav,
  SidebarFooter,
  useSidebar,
} from '../ui/Layout'
import { Menu, Plus } from 'iconoir-react'
import { SessionsProvider, useSessionsContext } from '../../contexts/SessionsContext'
import { SessionList } from '../sessions/SessionList'
import { NewSessionModal } from '../sessions/NewSessionModal'

export function AppLayout() {
  return (
    <SessionsProvider>
      <Layout className="!h-dvh">
        <Sidebar width="w-72">
          <SidebarHeader>
            <h1 className="text-lg font-semibold text-text-primary">Stargate</h1>
            <p className="text-xs text-text-secondary mt-0.5">Claude Code Chat</p>
          </SidebarHeader>

          <SidebarNav className="p-0">
            <SessionList />
          </SidebarNav>

          <SidebarFooter>
            <span>Stargate</span>
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

function MobileHeader() {
  const { toggle } = useSidebar()
  const navigate = useNavigate()
  const { create } = useSessionsContext()
  const [isNewSessionOpen, setIsNewSessionOpen] = useState(false)

  // Listen for custom event from HomeView's "New Session" button
  useEffect(() => {
    const handler = () => setIsNewSessionOpen(true)
    window.addEventListener('stargate:new-session', handler)
    return () => window.removeEventListener('stargate:new-session', handler)
  }, [])

  const handleCreate = async (config: {
    title?: string
    role?: string
    projectName?: string
    projectDir?: string
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
      <div className="flex items-center gap-3 px-3 py-2 border-b border-border bg-surface-secondary md:hidden">
        <button
          type="button"
          onClick={toggle}
          className="p-2.5 -m-1 rounded text-text-secondary hover:text-text-primary active:bg-surface-tertiary transition-colors touch-manipulation"
          aria-label="Toggle navigation"
        >
          <Menu className="w-5 h-5" />
        </button>
        <span className="text-sm font-medium text-text-primary">Stargate</span>
        <button
          type="button"
          onClick={() => setIsNewSessionOpen(true)}
          className="ml-auto p-2.5 -m-1 rounded text-teal-400 hover:text-teal-300 active:bg-surface-tertiary transition-colors touch-manipulation"
          aria-label="New session"
        >
          <Plus className="w-5 h-5" />
        </button>
      </div>
    </>
  )
}
