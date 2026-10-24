// A card per page of an index (VRT-73): what it is for, in one line, and a way in.
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import type { Page } from '@/components/layout/navigation'

export function HubCards({ pages }: { pages: Page[] }) {
  const shown = pages.filter((p) => !p.show || p.show())
  if (shown.length === 0) return null
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {shown.map(({ to, label, description, icon: Icon }) => (
        <Link
          key={to}
          to={to}
          className="group flex items-start gap-3 rounded-lg border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/40"
        >
          <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Icon className="size-4" />
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-sm font-medium">{label}</span>
            <span className="text-sm text-muted-foreground">{description}</span>
          </span>
          <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
        </Link>
      ))}
    </div>
  )
}
