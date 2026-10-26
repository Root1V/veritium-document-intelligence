// The data to review (VRT-77, VRT-108): the cases on the left, the one that
// has waited longest first, one line each; the chosen case's data beside
// them, each one to correct or to confirm as it is. When a case is done, the
// next one opens.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, CircleCheck, Loader2 } from 'lucide-react'
import { ReviewRow } from '@/components/review/ReviewRow'
import { useInvestigationStats, useReviewQueue } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ReviewItem } from '@/types/api'

type Filter = 'all' | 'validation_issue' | 'low_confidence' | 'suggestion'

const FILTERS: { key: Filter; label: string; test: (i: ReviewItem) => boolean }[] = [
  { key: 'all', label: 'Todos', test: () => true },
  { key: 'validation_issue', label: 'No pasaron una validación', test: (i) => i.reason === 'validation_issue' },
  { key: 'low_confidence', label: 'Lectura dudosa', test: (i) => i.reason === 'low_confidence' },
  { key: 'suggestion', label: 'Con sugerencia de la IA', test: (i) => i.suggestion !== null },
]

function since(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return 'hoy'
  if (days === 1) return 'desde ayer'
  return `hace ${days} días`
}

/** Waiting a week or more is amber; a month, red. */
const ageTone = (iso: string) => {
  const days = (Date.now() - new Date(iso).getTime()) / 86_400_000
  return days >= 30 ? 'text-red-700 dark:text-red-400' : days >= 7 ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground'
}

export function ReviewQueuePage() {
  const { data: items, isLoading, isError } = useReviewQueue()
  const { data: stats } = useInvestigationStats()
  const [filter, setFilter] = useState<Filter>('all')
  const [selected, setSelected] = useState<string | null>(null)

  const all = items ?? []
  const shown = all.filter(FILTERS.find((f) => f.key === filter)!.test)
  const groups: { caseId: string; caseRef: string; items: ReviewItem[] }[] = []
  for (const item of shown) {
    const group = groups.find((g) => g.caseId === item.case_id)
    if (group) group.items.push(item)
    else groups.push({ caseId: item.case_id, caseRef: item.case_ref ?? `Expediente ${item.case_id.slice(0, 8)}`, items: [item] })
  }
  // The chosen case, or — once it has nothing left — the next one waiting.
  const open = groups.find((g) => g.caseId === selected) ?? groups[0]
  const cases = new Set(all.map((i) => i.case_id)).size

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Campos por revisar</h1>
        <p className="text-muted-foreground">
          {all.length === 0
            ? 'Datos que la lectura automática no pudo confirmar sola.'
            : `${all.length} ${all.length === 1 ? 'dato' : 'datos'} en ${cases} ${cases === 1 ? 'expediente' : 'expedientes'}. Corrige lo que se leyó mal o confirma lo que está bien: las dos quedan en la auditoría.`}
        </p>
      </div>

      {all.length > 0 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar">
          {FILTERS.map((f) => {
            const n = all.filter(f.test).length
            if (f.key !== 'all' && n === 0) return null
            return (
              <button
                key={f.key}
                type="button"
                aria-pressed={filter === f.key}
                onClick={() => setFilter(f.key)}
                className={cn('rounded-full border px-3 py-1 text-xs font-medium transition', filter === f.key ? 'border-primary bg-primary text-primary-foreground' : 'bg-card hover:border-primary/40')}
              >
                {f.label} <span className="tabular-nums opacity-80">{n}</span>
              </button>
            )
          })}
        </div>
      )}

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudo cargar la cola: el servidor de Veritium no responde.</p>
      ) : all.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border-2 border-dashed py-16 text-center">
          <CircleCheck className="size-10 text-emerald-600" />
          <span className="text-lg font-medium">Todo al día</span>
          <span className="text-sm text-muted-foreground">No hay datos esperando revisión.</span>
        </div>
      ) : !open ? (
        <p className="text-sm text-muted-foreground">Nada con este filtro.</p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,22rem)_1fr]">
          <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
            {groups.map((g) => {
              const active = g.caseId === open.caseId
              const first = g.items[0]
              return (
                <button
                  key={g.caseId}
                  type="button"
                  onClick={() => setSelected(g.caseId)}
                  className={cn('flex items-start gap-3 border-b px-4 py-3 text-left transition last:border-0 hover:bg-muted/50', active && 'bg-primary/5 shadow-[inset_3px_0_0] shadow-primary')}
                >
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate font-semibold">{g.caseRef}</span>
                      <span className={cn('shrink-0 text-xs', ageTone(first.created_at))}>{since(first.created_at)}</span>
                    </span>
                    <span className="truncate text-xs text-muted-foreground">{g.items.map((i) => i.label).join(' · ')}</span>
                    <span className="text-xs text-muted-foreground">
                      {g.items.length === 1 ? '1 dato' : `${g.items.length} datos`}
                      {g.items.some((i) => i.suggestion) && <span className="text-sky-700 dark:text-sky-300"> · con sugerencia de la IA</span>}
                    </span>
                  </span>
                  <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" />
                </button>
              )
            })}
          </div>

          <section className="overflow-hidden rounded-xl border bg-card lg:sticky lg:top-16 lg:max-h-[calc(100svh-5rem)] lg:overflow-y-auto">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b bg-muted/40 px-4 py-3">
              <Link to={`/cases/${open.caseId}`} className="text-lg font-semibold hover:underline">
                {open.caseRef}
              </Link>
              <span className={cn('text-xs', ageTone(open.items[0].created_at))}>
                {open.items.length === 1 ? '1 dato' : `${open.items.length} datos`} · espera {since(open.items[0].created_at)}
              </span>
            </div>
            <div className="flex flex-col divide-y">
              {open.items.map((item) => (
                <ReviewRow key={item.id} item={item} />
              ))}
            </div>
          </section>
        </div>
      )}

      {stats && stats.investigated > 0 && (
        <p className="text-xs text-muted-foreground" title="De las correcciones que sugirió la IA y que alguien ya resolvió.">
          Sugerencias de la IA: {stats.acceptance_rate === null ? '—' : `${Math.round(stats.acceptance_rate * 100)}% aceptadas`} · {stats.accepted} aplicadas,{' '}
          {stats.overridden} corregidas de otra forma, {stats.dismissed} descartadas.
        </p>
      )}
    </div>
  )
}
