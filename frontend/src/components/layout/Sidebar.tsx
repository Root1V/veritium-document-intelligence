import type { ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { FileStack, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useReviewQueue } from '@/lib/queries'
import { GROUPS, type Section } from '@/components/layout/navigation'

function isActive(section: Section, pathname: string): boolean {
  if (section.end) return pathname === section.to
  return section.match.some((p) => pathname === p || pathname.startsWith(`${p}/`))
}

/** How many fields wait for a person; shown beside "Revisar" (on its icon when the menu is folded). */
function PendingCount({ collapsed }: { collapsed: boolean }) {
  const { data } = useReviewQueue()
  if (!data?.length) return null
  return (
    <span
      className={cn(
        'rounded-full bg-amber-400 font-semibold text-amber-950',
        collapsed ? 'absolute -top-2 left-2.5 min-w-4 px-1 text-center text-[10px] leading-4 ring-2 ring-sidebar' : 'ml-auto px-2 text-xs',
      )}
    >
      {data.length > 99 ? '99+' : data.length}
    </span>
  )
}

/** The name of an icon of the folded menu, beside it on hover or focus. */
function Hint({ children }: { children: ReactNode }) {
  return (
    <span className="pointer-events-none absolute top-1/2 left-full z-50 ml-3 -translate-y-1/2 rounded-md bg-foreground px-2 py-1 text-xs font-medium whitespace-nowrap text-background opacity-0 shadow-md transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
      {children}
    </span>
  )
}

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { pathname } = useLocation()

  return (
    <aside
      className={cn(
        'sticky top-0 z-30 flex h-svh shrink-0 flex-col bg-sidebar text-sidebar-foreground transition-[width] duration-200',
        collapsed ? 'w-16' : 'w-60',
      )}
    >
      <div className={cn('flex items-center gap-2 py-4', collapsed ? 'justify-center px-2' : 'px-5')}>
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
          <FileStack className="size-4" />
        </div>
        {!collapsed && (
          <div className="flex flex-col leading-tight">
            <span className="text-base font-semibold tracking-tight text-white">Veritium</span>
            <span className="text-xs text-sidebar-foreground/60">Plataforma documental</span>
          </div>
        )}
      </div>

      <nav className={cn('flex flex-1 flex-col gap-5 py-2', collapsed ? 'px-2' : 'overflow-y-auto px-3')} aria-label="Principal">
        {GROUPS.map((group) => {
          const sections = group.sections.filter((s) => s.show())
          if (sections.length === 0) return null
          return (
            <div key={group.label ?? 'trabajo'} className="flex flex-col gap-0.5">
              {group.label &&
                (collapsed ? (
                  <span className="mx-3 mb-1 border-t border-sidebar-foreground/15" aria-hidden />
                ) : (
                  <span className="px-3 pb-1 text-xs font-medium tracking-wide text-sidebar-foreground/50 uppercase">{group.label}</span>
                ))}
              {sections.map((section) => {
                const active = isActive(section, pathname)
                const Icon = section.icon
                return (
                  <NavLink
                    key={section.to}
                    to={section.to}
                    aria-current={active ? 'page' : undefined}
                    aria-label={collapsed ? section.label : undefined}
                    className={cn(
                      'group relative flex items-center gap-3 rounded-md py-2 text-sm font-medium transition-colors',
                      collapsed ? 'justify-center px-0' : 'px-3',
                      active
                        ? 'bg-sidebar-primary text-sidebar-primary-foreground shadow-sm'
                        : 'text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                    )}
                  >
                    <span className="relative">
                      <Icon className="size-4" />
                      {collapsed && section.to === '/review' && <PendingCount collapsed />}
                    </span>
                    {collapsed ? <Hint>{section.label}</Hint> : section.label}
                    {!collapsed && section.to === '/review' && <PendingCount collapsed={false} />}
                  </NavLink>
                )
              })}
            </div>
          )
        })}
      </nav>

      <div className={cn('border-t border-sidebar-foreground/10 py-3', collapsed ? 'px-2' : 'px-3')}>
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? 'Mostrar el menú' : 'Plegar el menú'}
          className={cn(
            'group relative flex w-full items-center gap-3 rounded-md py-2 text-sm text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
            collapsed ? 'justify-center' : 'px-3',
          )}
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          {collapsed ? <Hint>Mostrar el menú</Hint> : 'Plegar el menú'}
        </button>
      </div>
    </aside>
  )
}
