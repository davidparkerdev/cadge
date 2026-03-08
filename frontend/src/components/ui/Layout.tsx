import {
  type HTMLAttributes,
  type ReactNode,
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
} from 'react'
import { cn } from '../../lib/cn'

// ---------------------------------------------------------------------------
// Sidebar context -- lets Layout, Sidebar and MainContent coordinate on mobile
// ---------------------------------------------------------------------------

interface SidebarContextValue {
  isOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
}

const SidebarContext = createContext<SidebarContextValue>({
  isOpen: false,
  open: () => {},
  close: () => {},
  toggle: () => {},
})

export function useSidebar() {
  return useContext(SidebarContext)
}

// ---------------------------------------------------------------------------
// Layout -- root flex container + sidebar state provider
// ---------------------------------------------------------------------------

export interface LayoutProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
}

export function Layout({ className, children, ...props }: LayoutProps) {
  const [isOpen, setIsOpen] = useState(false)
  const open = useCallback(() => setIsOpen(true), [])
  const close = useCallback(() => setIsOpen(false), [])
  const toggle = useCallback(() => setIsOpen((v) => !v), [])

  // Close sidebar on route changes (popstate fires on back/forward)
  useEffect(() => {
    const handler = () => setIsOpen(false)
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [])

  return (
    <SidebarContext.Provider value={{ isOpen, open, close, toggle }}>
      <div
        className={cn('flex h-screen bg-surface-primary safe-area-top', className)}
        {...props}
      >
        {children}
      </div>
    </SidebarContext.Provider>
  )
}

// ---------------------------------------------------------------------------
// Sidebar -- hidden on mobile, slides in as overlay when open
// ---------------------------------------------------------------------------

export interface SidebarProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode
  width?: string
}

export function Sidebar({
  className,
  children,
  width = 'w-56',
  ...props
}: SidebarProps) {
  const { isOpen, close } = useSidebar()

  return (
    <>
      {/* Backdrop -- mobile only, shown when sidebar is open */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={close}
          aria-hidden="true"
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={cn(
          // Base
          'bg-surface-secondary border-r border-border flex flex-col z-50',
          // Mobile: fixed overlay that slides in/out, with safe area for notch
          'fixed inset-y-0 left-0 transition-transform duration-200 ease-in-out safe-area-top',
          isOpen ? 'translate-x-0' : '-translate-x-full',
          // Desktop (md+): static position, always visible, no transform
          'md:static md:translate-x-0 md:transition-none',
          width,
          className
        )}
        {...props}
      >
        {children}
      </aside>
    </>
  )
}

// ---------------------------------------------------------------------------
// SidebarHeader
// ---------------------------------------------------------------------------

export interface SidebarHeaderProps extends HTMLAttributes<HTMLDivElement> {}

export function SidebarHeader({ className, ...props }: SidebarHeaderProps) {
  return (
    <div
      className={cn('p-4 border-b border-border', className)}
      {...props}
    />
  )
}

// ---------------------------------------------------------------------------
// SidebarNav -- clicking a link auto-closes sidebar on mobile
// ---------------------------------------------------------------------------

export interface SidebarNavProps extends HTMLAttributes<HTMLElement> {}

export function SidebarNav({ className, children, ...props }: SidebarNavProps) {
  const { close } = useSidebar()

  return (
    <nav
      className={cn('flex-1 p-3 overflow-y-auto', className)}
      onClick={(e) => {
        // Auto-close on mobile when a link or nav item is clicked
        const target = e.target as HTMLElement
        if (target.closest('a, [data-nav-item]')) {
          close()
        }
        props.onClick?.(e)
      }}
      {...props}
    >
      {children}
    </nav>
  )
}

// ---------------------------------------------------------------------------
// SidebarFooter
// ---------------------------------------------------------------------------

export interface SidebarFooterProps extends HTMLAttributes<HTMLDivElement> {}

export function SidebarFooter({ className, ...props }: SidebarFooterProps) {
  return (
    <div
      className={cn(
        'p-4 border-t border-border text-text-secondary text-xs',
        className
      )}
      {...props}
    />
  )
}
