// Business units (VRT-57, VRT-101), for the platform team (VRT-71): one card
// per unit with how many people work in it — none is said in amber, since
// nobody gets in until its groups exist in the corporate account. Creating,
// renaming and deleting (VRT-72) go through a dialog; the groups stay folded.
import { useState } from 'react'
import { Building2, Loader2, Pencil, Plus } from 'lucide-react'
import { Groups, UnitDialog } from '@/components/units/UnitDialog'
import { Button } from '@/components/ui/button'
import { getUnit } from '@/lib/auth'
import { useBusinessUnits } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { BusinessUnitView } from '@/types/api'

function UnitCard({ unit, current, onOpen }: { unit: BusinessUnitView; current: boolean; onOpen: () => void }) {
  return (
    <div className="flex flex-col gap-4 rounded-xl border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <button type="button" onClick={onOpen} className="group flex min-w-0 items-start gap-3 text-left">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Building2 className="size-5" />
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="flex flex-wrap items-center gap-2">
              <span className="truncate font-semibold group-hover:underline">{unit.name}</span>
              {current && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">Estás aquí</span>}
            </span>
            <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
              <span className={cn('size-2 shrink-0 rounded-full', unit.people ? 'bg-emerald-500' : 'bg-amber-500')} />
              {unit.people === 0 ? 'Nadie entra todavía' : unit.people === 1 ? '1 persona' : `${unit.people} personas`}
            </span>
          </span>
        </button>
        <Button size="icon" variant="ghost" aria-label={`Editar ${unit.name}`} onClick={onOpen}>
          <Pencil className="size-4" />
        </Button>
      </div>
      <details className="mt-auto border-t pt-3 text-sm">
        <summary className="cursor-pointer text-xs text-muted-foreground select-none hover:text-foreground">
          {unit.people ? 'Grupos en la cuenta corporativa' : 'Crea sus grupos en la cuenta corporativa para dar acceso'}
        </summary>
        <div className="mt-2">
          <Groups unit={unit} />
        </div>
      </details>
    </div>
  )
}

export function BusinessUnitsPage() {
  const { data: units, isLoading, isError } = useBusinessUnits()
  const [open, setOpen] = useState<{ unit: BusinessUnitView | null } | null>(null)
  const here = getUnit()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Unidades de negocio</h1>
          <p className="text-muted-foreground">
            Cada unidad ve solo sus expedientes, procesos, sistemas conectados y revisiones. Quién trabaja en cada una, y con qué rol, se define en la cuenta
            corporativa: la persona entra al grupo de la unidad y su rol se aplica en su siguiente ingreso.
          </p>
        </div>
        <Button onClick={() => setOpen({ unit: null })}>
          <Plus className="size-4" /> Nueva unidad
        </Button>
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar las unidades: el servidor de Veritium no responde.</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {(units ?? []).map((u) => (
            <UnitCard key={u.key} unit={u} current={u.key === here} onOpen={() => setOpen({ unit: u })} />
          ))}
          <button
            type="button"
            onClick={() => setOpen({ unit: null })}
            className="flex min-h-36 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center text-sm text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
          >
            <Plus className="size-5" />
            <span className="font-medium">Nueva unidad</span>
            <span className="text-xs">En blanco o con procesos de ejemplo.</span>
          </button>
        </div>
      )}

      {open && <UnitDialog key={open.unit?.key ?? 'new'} unit={open.unit} onClose={() => setOpen(null)} />}
    </div>
  )
}
