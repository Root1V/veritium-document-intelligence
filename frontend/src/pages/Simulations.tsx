// Try a profile change before publishing it (VRT-44): which decisions would
// change over past cases, or — in shadow — over the new ones as they
// arrive. Told for an operator or an executive; nothing here touches a
// case or notifies anyone.
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorDetail } from '@/lib/apiErrors'
import { isAdmin } from '@/lib/auth'
import { cn } from '@/lib/utils'
import { VERDICT_LABEL, VERDICT_VARIANT } from '@/lib/verdict'
import { useProcessProfiles, useSimulation, useSimulations, useStartSimulation, useStopSimulation } from '@/lib/queries'
import type { SimulationView, VerdictDecision } from '@/types/api'

const date = (iso: string) =>
  new Date(iso).toLocaleString('es-PE', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
const VERSION_STATUS: Record<string, string> = {
  draft: 'borrador',
  published: 'publicada',
  retired: 'retirada',
}

function Verdict({ value }: { value: VerdictDecision | null }) {
  if (!value) return <Badge variant="outline">sin decisión</Badge>
  return <Badge variant={VERDICT_VARIANT[value]}>{VERDICT_LABEL[value]}</Badge>
}

function headline(s: SimulationView): string {
  const { cases, changed, failed } = s.summary
  const decided = cases - failed
  if (s.kind === 'shadow') {
    if (!cases) return 'En sombra: todavía no llegó ningún expediente nuevo de este proceso.'
    return `En sombra: ${decided} expedientes nuevos evaluados; en ${decided - changed} decidió lo mismo que hoy y en ${changed} decidió distinto.`
  }
  if (s.status === 'pending' || s.status === 'running') return `Probando con expedientes pasados… ${cases} revisados hasta ahora.`
  if (!cases) return 'No había expedientes pasados de este proceso para probar.'
  if (!changed) return `De ${decided} expedientes, ninguno cambiaría de decisión.`
  return `De ${decided} expedientes, ${changed} cambiarían de decisión.`
}

function NewTest({ onStarted }: { onStarted: (id: string) => void }) {
  const [params] = useSearchParams()
  const { data: profiles } = useProcessProfiles()
  const start = useStartSimulation()
  const [profileKey, setProfileKey] = useState(params.get('profile') ?? '')
  const [version, setVersion] = useState(params.get('version') ?? '')
  const [kind, setKind] = useState<'what_if' | 'shadow'>('what_if')
  const [limit, setLimit] = useState('50')
  const profile = profiles?.find((p) => p.key === profileKey)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Probar un cambio</CardTitle>
        <CardDescription>Elige el proceso y la versión que quieres probar, normalmente el borrador que estás preparando.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-sm">
        <div className="flex flex-wrap gap-3">
          <Select
            value={profileKey}
            onValueChange={(k) => {
              setProfileKey(k)
              setVersion('')
            }}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="Proceso" />
            </SelectTrigger>
            <SelectContent>
              {(profiles ?? []).map((p) => (
                <SelectItem key={p.key} value={p.key}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={version} onValueChange={setVersion} disabled={!profile}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="Versión a probar" />
            </SelectTrigger>
            <SelectContent>
              {(profile?.versions ?? []).map((v) => (
                <SelectItem key={v.version} value={String(v.version)}>
                  Versión {v.version} · {VERSION_STATUS[v.status] ?? v.status}
                  {v.version === profile?.active_version && ' (en uso)'}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {(
            [
              [
                'what_if',
                'Con expedientes pasados',
                'Recalcula la decisión de los últimos expedientes con lo que ya se leyó de sus documentos. Tarda poco.',
              ],
              [
                'shadow',
                'En sombra con los nuevos',
                'Cada expediente nuevo se decide también con esta versión, sin afectar la decisión real, hasta que la detengas.',
              ],
            ] as const
          ).map(([value, title, text]) => (
            <button
              key={value}
              type="button"
              onClick={() => setKind(value)}
              className={cn(
                'flex flex-col gap-1 rounded-md border p-3 text-left',
                kind === value ? 'border-primary bg-primary/5' : 'hover:bg-muted/50',
              )}
            >
              <span className="font-medium">{title}</span>
              <span className="text-xs text-muted-foreground">{text}</span>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {kind === 'what_if' && (
            <Select value={limit} onValueChange={setLimit}>
              <SelectTrigger className="w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {['20', '50', '100', '200'].map((n) => (
                  <SelectItem key={n} value={n}>
                    Los últimos {n} expedientes
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Button
            disabled={!profileKey || !version || start.isPending}
            onClick={() =>
              start.mutate(
                {
                  profile_key: profileKey,
                  profile_version: Number(version),
                  kind,
                  case_limit: Number(limit),
                },
                {
                  onSuccess: (s) => {
                    onStarted(s.id)
                    toast.success(kind === 'shadow' ? 'Sombra encendida: se aplicará a los próximos expedientes.' : 'Prueba en curso.')
                  },
                  onError: (e) => toast.error(errorDetail(e)),
                },
              )
            }
          >
            {start.isPending && <Loader2 className="size-4 animate-spin" />} Probar
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function Result({ id }: { id: string }) {
  const { data: s } = useSimulation(id)
  const stop = useStopSimulation()
  const [showSame, setShowSame] = useState(false)
  if (!s) return <Loader2 className="size-5 animate-spin text-muted-foreground" />
  const changed = s.cases.filter((c) => !c.error && c.actual_verdict !== c.simulated_verdict)
  const kept = s.cases.filter((c) => !c.error && c.actual_verdict === c.simulated_verdict)
  const otherReasons = kept.filter((c) => c.added_reasons.length || c.removed_reasons.length)
  const same = kept.filter((c) => !c.added_reasons.length && !c.removed_reasons.length)
  const failed = s.cases.filter((c) => c.error)
  const decisions = Array.from(new Set([...Object.keys(s.summary.before), ...Object.keys(s.summary.after)]))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {s.profile_key} · versión {s.profile_version}
          <Badge variant="outline">{s.kind === 'shadow' ? 'en sombra' : 'con expedientes pasados'}</Badge>
          {s.status === 'running' && s.kind === 'shadow' && <Badge>activa</Badge>}
          {s.status === 'stopped' && <Badge variant="outline">detenida</Badge>}
        </CardTitle>
        <CardDescription>
          Iniciada por {s.created_by} el {date(s.created_at)}
          {s.finished_at && ` · ${s.kind === 'shadow' ? 'detenida' : 'terminada'} el ${date(s.finished_at)}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 text-sm">
        <p className="text-base font-medium">{headline(s)}</p>
        {s.error && <p className="text-destructive">La prueba no pudo terminar: {s.error}</p>}

        {s.summary.transitions.length > 0 && (
          <div className="flex flex-col gap-2">
            {s.summary.transitions.map((t, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{t.count}</span> pasarían de <Verdict value={t.before} /> <ArrowRight className="size-4" />{' '}
                <Verdict value={t.after} />
              </div>
            ))}
          </div>
        )}

        {decisions.length > 0 && (
          <div className="grid max-w-md grid-cols-3 gap-y-1 text-sm">
            <span className="text-muted-foreground">Decisión</span>
            <span className="text-muted-foreground">Hoy</span>
            <span className="text-muted-foreground">Con el cambio</span>
            {decisions.map((d) => (
              <span key={d} className="contents">
                <span>{VERDICT_LABEL[d as VerdictDecision] ?? 'sin decisión'}</span>
                <span>{s.summary.before[d] ?? 0}</span>
                <span>{s.summary.after[d] ?? 0}</span>
              </span>
            ))}
          </div>
        )}

        {[
          ['Expedientes que cambiarían de decisión', changed],
          ['Misma decisión, con otros motivos', otherReasons],
        ].map(([title, group]) =>
          (group as typeof changed).length === 0 ? null : (
            <div key={title as string} className="flex flex-col gap-2">
              <span className="font-medium">{title as string}</span>
              {(group as typeof changed).map((c) => (
                <div key={c.case_id} className="flex flex-col gap-1 rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link to={`/cases/${c.case_id}`} className="font-medium underline-offset-4 hover:underline">
                      {c.case_ref ?? c.case_id.slice(0, 8)}
                    </Link>
                    <span className="text-muted-foreground">hoy</span> <Verdict value={c.actual_verdict} /> <ArrowRight className="size-4" />
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
                </div>
              ))}
            </div>
          ),
        )}

        {same.length > 0 && (
          <div className="flex flex-col gap-1">
            <button type="button" className="w-fit text-left text-muted-foreground underline" onClick={() => setShowSame(!showSame)}>
              {same.length} expedientes quedan igual {showSame ? '(ocultar)' : '(ver)'}
            </button>
            {showSame &&
              same.map((c) => (
                <span key={c.case_id} className="flex items-center gap-2 text-xs">
                  <Link to={`/cases/${c.case_id}`} className="underline-offset-4 hover:underline">
                    {c.case_ref ?? c.case_id.slice(0, 8)}
                  </Link>
                  <Verdict value={c.actual_verdict} />
                </span>
              ))}
          </div>
        )}

        {failed.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {failed.length} expedientes no se pudieron probar ({failed[0].error}
            ).
          </span>
        )}

        {isAdmin() && s.kind === 'shadow' && s.status === 'running' && (
          <div>
            <Button
              variant="outline"
              disabled={stop.isPending}
              onClick={() =>
                stop.mutate(s.id, {
                  onSuccess: () => toast.success('Sombra detenida.'),
                })
              }
            >
              Detener la sombra
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function SimulationsPage() {
  const { data: simulations, isLoading } = useSimulations()
  const [picked, setPicked] = useState<string | undefined>()
  const shown = picked ?? simulations?.[0]?.id
  const others = useMemo(() => (simulations ?? []).slice(0, 12), [simulations])

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Probar cambios</h1>
        <p className="text-muted-foreground">
          Antes de publicar una versión nueva de un proceso, mira qué decisiones cambiarían. Las pruebas no modifican ningún expediente ni avisan a
          nadie.
        </p>
      </div>

      {isAdmin() && <NewTest onStarted={setPicked} />}

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : others.length === 0 ? (
        <p className="text-sm text-muted-foreground">Todavía no hay pruebas.</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {others.map((s) => (
              <Button key={s.id} size="sm" variant={s.id === shown ? 'secondary' : 'ghost'} onClick={() => setPicked(s.id)}>
                {s.profile_key} v{s.profile_version} · {s.kind === 'shadow' ? 'sombra' : 'pasados'} · {date(s.created_at)}
              </Button>
            ))}
          </div>
          {shown && <Result id={shown} />}
        </>
      )}
    </div>
  )
}
