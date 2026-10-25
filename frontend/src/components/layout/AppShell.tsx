import type { ReactNode } from 'react'
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

export function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const hub = hubOf(pathname)
  // The assistant docks beside the page on wide screens instead of covering it.
  const { open: assistantOpen } = useAssistant()
  return (
    <div className="flex min-h-svh w-full bg-background">
      <Sidebar />
      <div className={cn('flex min-w-0 flex-1 flex-col transition-[margin]', assistantOpen && 'lg:mr-[420px]')}>
        <TopBar />
        <main className="flex-1 overflow-x-hidden px-8 py-6">
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
