import { NavLink, useLocation } from 'react-router-dom'
import { FileStack } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useReviewQueue } from '@/lib/queries'
import { GROUPS, type Section } from '@/components/layout/navigation'

function isActive(section: Section, pathname: string): boolean {
  if (section.end) return pathname === section.to
  return section.match.some((p) => pathname === p || pathname.startsWith(`${p}/`))
}

/** How many fields wait for a person; shown beside "Revisar". */
function PendingCount() {
  const { data } = useReviewQueue()
  if (!data?.length) return null
  return (
    <span className="ml-auto rounded-full bg-amber-100 px-2 text-xs font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">
      {data.length > 99 ? '99+' : data.length}
    </span>
  )
}

export function Sidebar() {
  const { pathname } = useLocation()

  return (
    <aside className="sticky top-0 flex h-svh w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2 px-5 py-4">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <FileStack className="size-4" />
        </div>
        <span className="text-base font-semibold tracking-tight">Veritium</span>
      </div>

      <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-2" aria-label="Principal">
        {GROUPS.map((group) => {
          const sections = group.sections.filter((s) => s.show())
          if (sections.length === 0) return null
          return (
            <div key={group.label ?? 'trabajo'} className="flex flex-col gap-0.5">
              {group.label && <span className="px-3 pb-1 text-xs font-medium text-muted-foreground">{group.label}</span>}
              {sections.map((section) => {
                const active = isActive(section, pathname)
                const Icon = section.icon
                return (
                  <NavLink
                    key={section.to}
                    to={section.to}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                      active
                        ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                        : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground',
                    )}
                  >
                    <Icon className="size-4" />
                    {section.label}
                    {section.to === '/review' && <PendingCount />}
                  </NavLink>
                )
              })}
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
