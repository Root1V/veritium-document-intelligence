// The people of the active unit (VRT-57, VRT-96), one block per role: what
// each role can do is said once, at the top, where it also filters. A person
// opens in a dialog to change their role or take them out of the unit.
import { useState } from 'react'
import { Building2, Loader2, Plus, Search, UserCog } from 'lucide-react'
import { PersonDialog } from '@/components/people/PersonDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getUnit, getUnits } from '@/lib/auth'
import { ROLES, initials } from '@/lib/people'
import { useUsers } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { AppUser, UserRole } from '@/types/api'

function PersonCard({ person, onOpen }: { person: AppUser; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className="group flex items-center gap-3 rounded-xl border bg-card p-3 text-left transition hover:border-primary/40 hover:shadow-sm">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{initials(person.name)}</span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-medium group-hover:underline">{person.name}</span>
        <span className="truncate text-xs text-muted-foreground">{person.email}</span>
      </span>
      {person.managed_by === 'idp' ? (
        <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground" title="Su rol viene del proveedor de identidad">
          <Building2 className="size-3" /> Corporativa
        </span>
      ) : (
        <UserCog className="size-4 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
      )}
    </button>
  )
}

export function UsersPage() {
  const { data: users, isLoading, isError } = useUsers()
  const unit = getUnits().find((u) => u.key === getUnit())?.name
  const [role, setRole] = useState<UserRole | null>(null)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<{ person: AppUser | null } | null>(null)
  const all = users ?? []
  const q = query.trim().toLocaleLowerCase('es')
  const shown = all.filter((u) => (!role || u.role === role) && (!q || `${u.name} ${u.email}`.toLocaleLowerCase('es').includes(q)))

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Personas</h1>
          <p className="text-muted-foreground">
            Quiénes trabajan en {unit ?? 'esta unidad'} y qué puede hacer cada uno. Quienes entran con su cuenta corporativa reciben su rol desde el proveedor de
            identidad.
          </p>
        </div>
        <Button onClick={() => setOpen({ person: null })}>
          <Plus className="size-4" /> Agregar persona
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {ROLES.map((r) => {
          const count = all.filter((u) => u.role === r.key).length
          const active = role === r.key
          return (
            <button
              key={r.key}
              type="button"
              onClick={() => setRole(active ? null : r.key)}
              className={cn('flex flex-col gap-1 rounded-xl border bg-card p-4 text-left transition hover:border-primary/40', active && 'border-primary ring-1 ring-primary', !count && 'opacity-60')}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="font-semibold">{r.name}</span>
                {users && <span className="text-2xl font-semibold tabular-nums">{count}</span>}
              </span>
              <span className="text-xs text-muted-foreground">{r.can}</span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar por nombre o correo" className="pl-8" />
        </div>
        {(role || q) && (
          <Button size="sm" variant="ghost" onClick={() => (setRole(null), setQuery(''))}>
            Ver a todos
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudo cargar a las personas: el servidor de Veritium no responde.</p>
      ) : !shown.length ? (
        <p className="text-sm text-muted-foreground">{all.length ? 'Nadie coincide con la búsqueda.' : 'Aún no hay nadie en esta unidad.'}</p>
      ) : (
        ROLES.map((r) => {
          const list = shown.filter((u) => u.role === r.key)
          if (!list.length) return null
          return (
            <section key={r.key} className="rounded-2xl border bg-muted/40">
              <div className="flex flex-wrap items-center gap-2 rounded-t-2xl border-b bg-background px-4 py-3 sm:px-5">
                <h2 className="text-lg font-semibold tracking-tight">{r.name}</h2>
                <span className="rounded-full bg-background px-2 py-0.5 text-xs font-medium text-muted-foreground ring-1 ring-border">
                  {list.length === 1 ? '1 persona' : `${list.length} personas`}
                </span>
              </div>
              <div className="grid gap-3 p-4 sm:grid-cols-2 sm:p-5 xl:grid-cols-3">
                {list.map((u) => (
                  <PersonCard key={u.id} person={u} onOpen={() => setOpen({ person: u })} />
                ))}
              </div>
            </section>
          )
        })
      )}

      {open && <PersonDialog key={open.person?.id ?? 'new'} person={open.person} onClose={() => setOpen(null)} />}
    </div>
  )
}
