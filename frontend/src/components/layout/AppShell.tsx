import { useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { TABS, hubOf } from '@/components/layout/navigation'
import { useAssistant } from '@/lib/assistant'

/** The lists of a section, side by side (VRT-73): only on the lists themselves, not on a record. */
function SectionTabs({ pathname }: { pathname: string }) {
  const tabs = Object.values(TABS).find((group) => group.some((t) => t.to === pathname))
  if (!tabs) return null
  return (
    <nav className="mb-6 flex gap-1 border-b" aria-label="Sección">
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end
          className={({ isActive }) =>
            cn(
              '-mb-px border-b-2 px-3 pb-2 text-sm font-medium transition-colors',
              isActive ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground',
            )
          }
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  )
}

// The menu folded to its icons is a per-person convenience, remembered in the browser.
const COLLAPSED_KEY = 'idp_menu_collapsed'

function storedCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

export function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const hub = hubOf(pathname)
  const [collapsed, setCollapsed] = useState(storedCollapsed)
  // The assistant docks beside the page only while the page keeps the ~1040px
  // its widest layouts (xl) assume; on narrower screens it goes over the page,
  // which then keeps its own layout instead of squeezing.
  const { open: assistantOpen } = useAssistant()

  function toggle() {
    setCollapsed(!collapsed)
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? '0' : '1')
    } catch {
      // without storage it is just not remembered
    }
  }

  return (
    <div className="flex min-h-svh w-full bg-background">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <div
        className={cn(
          'flex min-w-0 flex-1 flex-col transition-[margin]',
          assistantOpen && (collapsed ? 'min-[1524px]:mr-[420px]' : 'min-[1700px]:mr-[420px]'),
        )}
      >
        <TopBar />
        <main className="flex-1 overflow-x-clip px-8 py-6">
          {hub && (
            <Link to={hub.to} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
              <ChevronLeft className="size-4" /> {hub.label}
            </Link>
          )}
          <SectionTabs pathname={pathname} />
          {children}
        </main>
      </div>
    </div>
  )
}
