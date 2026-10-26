// The cases (VRT-25, VRT-109): how many of each decision there are — each a
// filter in its traffic-light colour — then one line per case, its decision
// first. Deleting a case is done from inside it, not from every row.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, Loader2, Search } from 'lucide-react'
import { ProgressFunnel } from '@/components/cases/ProgressFunnel'
import { UploadLinkDialog } from '@/components/cases/UploadLinkDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { canExecute } from '@/lib/auth'
import { useCases, useProcessProfiles } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { VERDICT_LABEL } from '@/lib/verdict'
import type { CaseListItem } from '@/types/api'

export const DELETE_CASE =
  'Se eliminará para siempre el expediente con sus documentos, archivos, lecturas y hallazgos. Solo queda el registro de quién lo eliminó y por qué.'

const CHANNEL_LABEL: Record<string, string> = { online: 'En línea', backoffice: 'Oficina', bulk: 'Carga masiva' }

type State = 'continue' | 'human_review' | 'return_to_client' | 'running' | 'failed' | 'none'
const STATES: { key: State; label: string; hint: string; dot: string; text: string; ring: string }[] = [
  { key: 'continue', label: 'Continuar', hint: 'Todo en orden: sigue su curso.', dot: 'bg-emerald-500', text: 'text-emerald-700 dark:text-emerald-400', ring: 'ring-emerald-500' },
  { key: 'human_review', label: 'Revisión humana', hint: 'Una persona debe revisar algo.', dot: 'bg-amber-500', text: 'text-amber-700 dark:text-amber-400', ring: 'ring-amber-500' },
  { key: 'return_to_client', label: 'Devolver al cliente', hint: 'Falta algo que debe aportar el cliente.', dot: 'bg-red-500', text: 'text-red-700 dark:text-red-400', ring: 'ring-red-500' },
  { key: 'running', label: 'En proceso', hint: 'Todavía se están leyendo sus documentos.', dot: 'bg-sky-500', text: 'text-sky-700 dark:text-sky-400', ring: 'ring-sky-500' },
]
// Less frequent: filters beside the search, not tiles.
const OTHERS: typeof STATES = [
  { key: 'failed', label: 'No se pudo procesar', hint: 'Algún paso falló: ábrelo para reintentar.', dot: 'bg-slate-500', text: 'text-muted-foreground', ring: 'ring-slate-500' },
  { key: 'none', label: 'Sin decisión', hint: 'Terminó sin un proceso que decida.', dot: 'bg-muted-foreground/30', text: 'text-muted-foreground', ring: 'ring-border' },
]
const stateOf = (c: CaseListItem): State =>
  c.verdict ?? (c.status === 'processing' || c.status === 'uploaded' ? 'running' : c.status === 'failed' ? 'failed' : 'none')

function ago(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 60) return minutes <= 1 ? 'hace un momento' : `hace ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return hours === 1 ? 'hace 1 hora' : `hace ${hours} horas`
  const days = Math.round(hours / 24)
  return days === 1 ? 'ayer' : days < 30 ? `hace ${days} días` : new Date(iso).toLocaleDateString('es-PE', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function CasesPage() {
  const { data: cases, isLoading, isError } = useCases()
  const { data: profiles } = useProcessProfiles()
  const [state, setState] = useState<State | null>(null)
  const [query, setQuery] = useState('')
  const processName = (key: string) => profiles?.find((p) => p.key === key)?.name ?? key
  const all = cases ?? []
  const q = query.trim().toLocaleLowerCase('es')
  const shown = all.filter((c) => (!state || stateOf(c) === state) && (!q || (c.external_ref ?? c.id).toLocaleLowerCase('es').includes(q)))

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Expedientes</h1>
          <p className="text-muted-foreground">Cada expediente con su decisión. Ábrelo para ver el resultado completo y su evidencia.</p>
        </div>
        {canExecute() && <UploadLinkDialog />}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {STATES.map((s) => {
          const n = all.filter((c) => stateOf(c) === s.key).length
          const active = state === s.key
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => setState(active ? null : s.key)}
              className={cn('flex flex-col gap-1 rounded-xl border bg-card p-4 text-left transition hover:border-primary/40', active && `ring-2 ${s.ring}`, !n && 'opacity-60')}
            >
              <span className="flex items-center justify-between gap-2">
                <span className={cn('inline-flex items-center gap-2 font-semibold', s.text)}>
                  <span className={cn('size-2.5 rounded-full', s.dot)} /> {s.label}
                </span>
                <span className="text-2xl font-semibold tabular-nums">{cases ? n : '—'}</span>
              </span>
              <span className="text-xs text-muted-foreground">{s.hint}</span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar por referencia" className="pl-8" />
        </div>
        {OTHERS.map((o) => {
          const n = all.filter((c) => stateOf(c) === o.key).length
          if (!n) return null
          return (
            <button
              key={o.key}
              type="button"
              title={o.hint}
              onClick={() => setState(state === o.key ? null : o.key)}
              className={cn('inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition', state === o.key ? 'border-primary bg-primary text-primary-foreground' : 'bg-card hover:border-primary/40')}
            >
              <span className={cn('size-2 rounded-full', o.dot)} /> {o.label} <span className="opacity-70">{n}</span>
            </button>
          )
        })}
        {(state || q) && (
          <Button size="sm" variant="ghost" onClick={() => (setState(null), setQuery(''))}>
            Ver todos
          </Button>
        )}
        <span className="ml-auto text-xs text-muted-foreground">{all.length === 200 ? 'Los 200 más recientes' : `${all.length} expedientes`}</span>
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar los expedientes: el servidor de Veritium no responde.</p>
      ) : !shown.length ? (
        <p className="text-sm text-muted-foreground">{all.length ? 'Ningún expediente con este filtro.' : 'Todavía no llegó ningún expediente.'}</p>
      ) : (
        <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
          {shown.map((c) => {
            const s = [...STATES, ...OTHERS].find((x) => x.key === stateOf(c))
            const running = c.status !== 'completed' || c.progress.failed_documents > 0
            return (
              <Link key={c.id} to={`/cases/${c.id}`} className="group flex items-center gap-3 border-b px-4 py-3 transition last:border-0 hover:bg-muted/50">
                <span className={cn('size-2.5 shrink-0 rounded-full', s?.dot ?? 'bg-muted-foreground/30')} />
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold group-hover:underline">{c.external_ref ?? `Expediente ${c.id.slice(0, 8)}`}</span>
                    <span className="text-xs text-muted-foreground">
                      {c.profile ? processName(c.profile.key) : 'Sin proceso'} · {CHANNEL_LABEL[c.channel] ?? c.channel}
                    </span>
                  </span>
                  {running && (
                    <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      {c.progress.status_label}
                      <ProgressFunnel progress={c.progress} compact />
                    </span>
                  )}
                </span>
                <span className={cn('hidden w-40 shrink-0 text-sm font-medium sm:block', s?.text ?? 'text-muted-foreground')}>
                  {c.verdict ? VERDICT_LABEL[c.verdict] : s?.label ?? '—'}
                </span>
                <span className="w-28 shrink-0 text-right text-xs text-muted-foreground" title={new Date(c.created_at).toLocaleString('es-PE')}>
                  {ago(c.created_at)}
                </span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
