// Try a profile change before publishing it (VRT-44, VRT-92): the tests made,
// each with what it found in a word, and the chosen one in full — how many
// decisions would change, today against with the change, and the cases that
// change. Nothing here touches a case or notifies anyone.
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, FlaskConical, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { DeleteButton } from '@/components/DeleteButton'
import { ToneBadge } from '@/components/StatusBadge'
import { NewTestDialog } from '@/components/simulations/NewTestDialog'
import { isAdmin } from '@/lib/auth'
import type { Tone } from '@/lib/labels'
import { VERDICT_LABEL } from '@/lib/verdict'
import { useProcessProfiles, useSimulation, useSimulations, useStopSimulation } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { SimulationView, VerdictDecision } from '@/types/api'

const date = (iso: string) => new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
const VERDICT_TONE: Record<VerdictDecision, Tone> = { continue: 'ok', human_review: 'warn', return_to_client: 'bad' }

function Verdict({ value }: { value: VerdictDecision | null }) {
  return value ? <ToneBadge tone={VERDICT_TONE[value]} label={VERDICT_LABEL[value]} /> : <ToneBadge tone="neutral" label="Sin decisión" />
}

/** What a test found, in a word and a color. */
function outcome(s: SimulationView): { tone: Tone; label: string } {
  const { cases, changed, failed } = s.summary
  if (s.status === 'failed') return { tone: 'bad', label: 'No terminó' }
  if (s.kind === 'shadow' && s.status === 'running') return { tone: 'busy', label: changed ? `Activa · ${changed} distintas` : 'Activa' }
  if (s.status === 'pending' || s.status === 'running') return { tone: 'busy', label: 'Probando…' }
  if (cases - failed === 0) return { tone: 'neutral', label: 'Sin expedientes' }
  if (changed) return { tone: 'warn', label: changed === 1 ? '1 cambiaría' : `${changed} cambiarían` }
  return { tone: 'ok', label: 'Sin cambios' }
}

function headline(s: SimulationView): string {
  const { cases, changed, failed } = s.summary
  const decided = cases - failed
  if (s.kind === 'shadow') {
    if (!cases) return 'Todavía no llegó ningún expediente nuevo de este proceso.'
    return `${decided} expedientes nuevos evaluados: en ${decided - changed} decidió lo mismo que hoy y en ${changed} decidió distinto.`
  }
  if (s.status === 'pending' || s.status === 'running') return `Probando con expedientes pasados… ${cases} revisados hasta ahora.`
  if (!cases) return 'No había expedientes pasados de este proceso para probar.'
  if (!changed) return `Ninguno de los ${decided} expedientes cambiaría de decisión.`
  return `${changed} de ${decided} expedientes cambiarían de decisión.`
}

const BANNER: Record<Tone, string> = {
  ok: 'border-emerald-500/30 bg-emerald-500/5',
  warn: 'border-amber-500/30 bg-amber-500/5',
  bad: 'border-red-500/30 bg-red-500/5',
  busy: 'border-sky-500/30 bg-sky-500/5',
  neutral: 'bg-muted/40',
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border bg-card px-4 py-3">
      <span className={cn('text-2xl font-semibold tabular-nums', tone)}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

function Result({ id, onDeleted, processName }: { id: string; onDeleted: () => void; processName: (key: string) => string }) {
  const { data: s } = useSimulation(id)
  const stop = useStopSimulation()
  const [showSame, setShowSame] = useState(false)
  if (!s) return <Loader2 className="size-5 animate-spin text-muted-foreground" />
  const changed = s.cases.filter((c) => !c.error && c.actual_verdict !== c.simulated_verdict)
  const kept = s.cases.filter((c) => !c.error && c.actual_verdict === c.simulated_verdict)
  const otherReasons = kept.filter((c) => c.added_reasons.length || c.removed_reasons.length)
  const same = kept.filter((c) => !c.added_reasons.length && !c.removed_reasons.length)
  const failed = s.cases.filter((c) => c.error)
  const decisions = (['continue', 'human_review', 'return_to_client'] as const).filter((d) => s.summary.before[d] || s.summary.after[d])
  const found = outcome(s)
  const caseLink = (c: (typeof s.cases)[number]) => (
    <Link to={`/cases/${c.case_id}`} className="font-medium underline-offset-4 hover:underline">
      {c.case_ref ?? c.case_id.slice(0, 8)}
    </Link>
  )

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 className="text-lg font-semibold">
            {processName(s.profile_key)} · versión {s.profile_version}
          </h2>
          <p className="text-sm text-muted-foreground">
            {s.kind === 'shadow' ? 'En sombra con los nuevos' : `Con los últimos ${s.case_limit ?? ''} expedientes pasados`} · iniciada por {s.created_by} el {date(s.created_at)}
            {s.finished_at && ` · ${s.kind === 'shadow' ? 'detenida' : 'terminada'} el ${date(s.finished_at)}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {isAdmin() && s.kind === 'shadow' && s.status === 'running' && (
            <Button variant="outline" size="sm" disabled={stop.isPending} onClick={() => stop.mutate(s.id, { onSuccess: () => toast.success('Sombra detenida.') })}>
              Detener la sombra
            </Button>
          )}
          {isAdmin() && s.status !== 'running' && s.status !== 'pending' && (
            <DeleteButton path={`/v1/simulations/${s.id}`} label="Eliminar" question="Se eliminará para siempre esta prueba y su resultado. Ningún expediente cambia." onDone={onDeleted} />
          )}
        </div>
      </div>

      <div className={cn('flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3', BANNER[found.tone])}>
        <ToneBadge tone={found.tone} label={found.label} />
        <p className="font-medium">{headline(s)}</p>
      </div>
      {s.error && <p className="text-sm text-destructive">La prueba no pudo terminar: {s.error}</p>}

      {s.summary.cases > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Expedientes probados" value={s.summary.cases - s.summary.failed} />
          <Stat label="Cambiarían de decisión" value={changed.length} tone={changed.length ? 'text-amber-600 dark:text-amber-400' : undefined} />
          <Stat label="Igual, con otros motivos" value={otherReasons.length} />
          <Stat label="No se pudieron probar" value={failed.length} tone={failed.length ? 'text-red-600 dark:text-red-400' : undefined} />
        </div>
      )}

      {decisions.length > 0 && (
        <div className="overflow-hidden rounded-xl border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Decisión</th>
                <th className="px-4 py-2 text-right font-medium">Hoy</th>
                <th className="px-4 py-2 text-right font-medium">Con el cambio</th>
                <th className="px-4 py-2 text-right font-medium">Diferencia</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {decisions.map((d) => {
                const before = s.summary.before[d] ?? 0
                const after = s.summary.after[d] ?? 0
                return (
                  <tr key={d}>
                    <td className="px-4 py-2.5">
                      <Verdict value={d} />
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{before}</td>
                    <td className="px-4 py-2.5 text-right font-medium tabular-nums">{after}</td>
                    <td className={cn('px-4 py-2.5 text-right tabular-nums', after === before ? 'text-muted-foreground' : 'font-medium')}>
                      {after === before ? '—' : `${after > before ? '+' : ''}${after - before}`}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {s.summary.transitions.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Qué cambiaría</h3>
          {s.summary.transitions.map((t, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold tabular-nums">{t.count}</span> pasarían de <Verdict value={t.before} />
              <ArrowRight className="size-4 text-muted-foreground" /> <Verdict value={t.after} />
            </div>
          ))}
        </div>
      )}

      {(
        [
          ['Expedientes que cambiarían de decisión', changed],
          ['Misma decisión, con otros motivos', otherReasons],
        ] as const
      ).map(([title, group]) =>
        group.length === 0 ? null : (
          <div key={title} className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">
              {title} ({group.length})
            </h3>
            <ul className="divide-y overflow-hidden rounded-xl border bg-card">
              {group.map((c) => (
                <li key={c.case_id} className="flex flex-col gap-1.5 px-4 py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    {caseLink(c)}
                    <span className="text-muted-foreground">hoy</span> <Verdict value={c.actual_verdict} />
                    <ArrowRight className="size-4 text-muted-foreground" />
                    <span className="text-muted-foreground">con el cambio</span> <Verdict value={c.simulated_verdict} />
                  </div>
                  {c.removed_reasons.map((r) => (
                    <span key={r} className="text-xs text-emerald-700 dark:text-emerald-400">
                      Ya no diría: {r}
                    </span>
                  ))}
                  {c.added_reasons.map((r) => (
                    <span key={r} className="text-xs text-red-700 dark:text-red-400">
                      Diría además: {r}
                    </span>
                  ))}
                </li>
              ))}
            </ul>
          </div>
        ),
      )}

      {same.length > 0 && (
        <div className="flex flex-col gap-2">
          <button type="button" className="w-fit text-sm text-primary hover:underline" onClick={() => setShowSame(!showSame)}>
            {showSame ? 'Ocultar' : 'Ver'} los {same.length} expedientes que quedan igual
          </button>
          {showSame && (
            <ul className="grid gap-x-6 gap-y-1.5 rounded-xl border bg-card px-4 py-3 text-sm sm:grid-cols-2 xl:grid-cols-3">
              {same.map((c) => (
                <li key={c.case_id} className="flex items-center justify-between gap-2">
                  {caseLink(c)}
                  <Verdict value={c.actual_verdict} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {failed.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {failed.length} expedientes no se pudieron probar ({failed[0].error}).
        </p>
      )}
    </div>
  )
}

export function SimulationsPage() {
  const [params, setParams] = useSearchParams()
  const { data: simulations, isLoading, isError } = useSimulations()
  const { data: profiles } = useProcessProfiles()
  const processName = (key: string) => profiles?.find((p) => p.key === key)?.name ?? key
  const [picked, setPicked] = useState<string | undefined>()
  // Coming from a process ("Probar" on its draft), the test opens ready to start.
  const [creating, setCreating] = useState(isAdmin() && params.has('profile'))
  const shown = picked ?? simulations?.[0]?.id

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Probar cambios</h1>
          <p className="text-muted-foreground">
            Antes de publicar una versión nueva de un proceso, mira qué decisiones cambiarían. Las pruebas no modifican ningún expediente ni avisan a nadie.
          </p>
        </div>
        {isAdmin() && (
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Nueva prueba
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar las pruebas: el servidor de Veritium no responde.</p>
      ) : !simulations?.length ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-6 py-12 text-center">
          <FlaskConical className="size-8 text-muted-foreground" />
          <p className="font-medium">Todavía no hay pruebas</p>
          <p className="max-w-md text-sm text-muted-foreground">
            Cuando prepares un cambio en un proceso, pruébalo aquí con los expedientes pasados para ver qué decisiones cambiarían antes de publicarlo.
          </p>
          {isAdmin() && (
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" /> Nueva prueba
            </Button>
          )}
        </div>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[18rem_1fr]">
          <aside className="flex flex-col gap-2 xl:sticky xl:top-20">
            <span className="text-xs font-medium text-muted-foreground">Pruebas ({simulations.length})</span>
            <ul className="flex flex-col gap-1.5">
              {simulations.map((s) => {
                const found = outcome(s)
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => setPicked(s.id)}
                      className={cn(
                        'flex w-full flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-left transition',
                        s.id === shown ? 'border-primary bg-primary/5' : 'bg-card hover:border-primary/40',
                      )}
                    >
                      <span className="text-sm font-medium">
                        {processName(s.profile_key)} · v{s.profile_version}
                      </span>
                      <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <ToneBadge tone={found.tone} label={found.label} />
                        {s.kind === 'shadow' ? 'En sombra' : 'Pasados'} · {date(s.created_at)}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </aside>
          <div className="min-w-0 rounded-2xl border bg-muted/20 p-5">
            {shown && <Result key={shown} id={shown} onDeleted={() => setPicked(undefined)} processName={processName} />}
          </div>
        </div>
      )}

      {creating && (
        <NewTestDialog
          initial={{ profile: params.get('profile') ?? undefined, version: params.get('version') ?? undefined }}
          onStarted={(id) => {
            setPicked(id)
            setCreating(false)
            setParams({}, { replace: true })
          }}
          onClose={() => {
            setCreating(false)
            setParams({}, { replace: true })
          }}
        />
      )}
    </div>
  )
}
