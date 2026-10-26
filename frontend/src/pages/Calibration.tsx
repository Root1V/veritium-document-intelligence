// How reliable the automatic reading is, data by data (VRT-43, VRT-106), told
// for an operator or an executive. The measurement's state and what can be
// done with it come first; then the gap between how sure the system says it
// is and how often it is right; then a traffic-light board — which data can
// pass alone, which with care, which a person should always check — and how
// much could pass unreviewed. The statistics (ECE, Brier, bins) stay folded.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CircleAlert, FlaskConical, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { DeleteButton } from '@/components/DeleteButton'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { errorDetail } from '@/lib/apiErrors'
import { isAdmin } from '@/lib/auth'
import { useCalibration, useCalibrations, useComputeCalibration, useSetActiveCalibration } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { CalibrationDetail } from '@/types/api'

type Field = CalibrationDetail['fields'][number]

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`)
const date = (iso: string) => new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
const errorsIn = (target: number) => `1 error cada ${Math.round(1 / target)} datos`

// The traffic light: how often the data is actually right.
const LEVELS = [
  { min: 0.95, title: 'Pueden pasar solos', hint: 'Aciertan 95 de cada 100 veces o más.', dot: 'bg-emerald-500', text: 'text-emerald-700 dark:text-emerald-400', band: 'border-t-emerald-500' },
  { min: 0.85, title: 'Con cuidado', hint: 'Revísalos cuando el documento es dudoso.', dot: 'bg-amber-500', text: 'text-amber-700 dark:text-amber-400', band: 'border-t-amber-500' },
  { min: 0, title: 'Revisar siempre', hint: 'Aciertan menos de 85 de cada 100 veces.', dot: 'bg-red-500', text: 'text-red-700 dark:text-red-400', band: 'border-t-red-500' },
] as const
const levelOf = (accuracy: number) => LEVELS.find((l) => accuracy >= l.min) ?? LEVELS[2]

function FieldCard({ field }: { field: Field }) {
  const right = Math.round(field.accuracy * field.count)
  const overconfident = field.mean_confidence !== null && field.mean_confidence - field.accuracy > 0.1
  return (
    <div className="flex flex-col gap-1 rounded-lg border bg-background p-3">
      <span className="flex items-baseline justify-between gap-2">
        <span className="font-medium">{field.label}</span>
        <span className="text-sm font-semibold tabular-nums">{pct(field.accuracy)}</span>
      </span>
      <span className="text-xs text-muted-foreground">
        {field.document_type_name} · acertó {right} de {field.count}
      </span>
      {overconfident && <span className="text-xs text-red-700 dark:text-red-400">El sistema decía estar seguro al {pct(field.mean_confidence)}.</span>}
      {field.preliminary && <span className="text-xs text-muted-foreground italic">Orientativo: pocas comprobaciones.</span>}
    </div>
  )
}

function Stat({ label, value, note, tone }: { label: string; value: string; note: string; tone?: 'bad' }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border bg-card p-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={cn('text-2xl font-semibold', tone === 'bad' && 'text-red-700 dark:text-red-400')}>{value}</span>
      <span className="text-xs text-muted-foreground">{note}</span>
    </div>
  )
}

export function CalibrationPage() {
  const { data: versions, isLoading } = useCalibrations()
  const compute = useComputeCalibration()
  const setActive = useSetActiveCalibration()
  const [picked, setPicked] = useState<number | undefined>()
  const shown = picked ?? versions?.[0]?.version
  const { data: detail } = useCalibration(shown)
  const inUse = versions?.find((v) => v.status === 'active')
  const admin = isAdmin()

  const total = detail ? detail.fields.reduce((n, f) => n + f.count, 0) : 0
  const right = detail ? detail.fields.reduce((n, f) => n + Math.round(f.accuracy * f.count), 0) : 0
  const accuracy = total ? right / total : null
  const said = detail?.fields.filter((f) => f.mean_confidence !== null) ?? []
  const meanSaid = said.length ? said.reduce((n, f) => n + (f.mean_confidence ?? 0) * f.count, 0) / said.reduce((n, f) => n + f.count, 0) : null
  const gap = meanSaid !== null && accuracy !== null ? meanSaid - accuracy : null
  const fewData = detail?.fields.some((f) => f.preliminary)
  const suggestions = detail?.report.suggestions ?? []
  const noneCanPass = suggestions.length > 0 && suggestions.every((s) => s.threshold === null)

  const update = () =>
    compute.mutate(undefined, {
      onSuccess: (v) => {
        setPicked(v.version)
        toast.success('Medición actualizada con los datos de hoy.')
      },
      onError: (e) => toast.error(errorDetail(e)),
    })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Confiabilidad de la lectura automática</h1>
          <p className="text-muted-foreground">Compara lo que el sistema leyó con lo que confirmaron personas, dato por dato: qué puede pasar solo y qué conviene que revise alguien.</p>
        </div>
        {admin && (
          <Button variant="outline" disabled={compute.isPending} onClick={update}>
            {compute.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} Actualizar medición
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : !detail ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border bg-card p-6 text-sm">
          <p className="text-muted-foreground">Todavía no hay mediciones. Para tener una, corre un conjunto de prueba con documentos reales y luego actualiza la medición.</p>
          <Button variant="outline" asChild>
            <Link to="/evaluation">
              <FlaskConical className="size-4" /> Ir a los conjuntos de prueba
            </Link>
          </Button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border bg-muted/40 px-4 py-3 text-sm">
            {(versions?.length ?? 0) > 1 ? (
              <Select value={String(shown)} onValueChange={(v) => setPicked(Number(v))}>
                <SelectTrigger className="h-8 w-64">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {versions!.map((v) => (
                    <SelectItem key={v.version} value={String(v.version)}>
                      Medición del {date(v.created_at)}
                      {v.status === 'active' && ' · en uso'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <span className="font-medium">Medición del {date(detail.created_at)}</span>
            )}
            <span className="text-muted-foreground">{total === 1 ? '1 comprobación' : `${total} comprobaciones`}</span>
            {detail.status === 'active' ? (
              <span className="inline-flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-400">
                <span className="size-2 rounded-full bg-emerald-500" /> En uso en la cola de revisión desde el {detail.activated_at && date(detail.activated_at)}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                <span className="size-2 rounded-full bg-muted-foreground/40" />
                {inUse ? `No está en uso: se usa la del ${date(inUse.created_at)}` : 'No está en uso: la cola usa la seguridad que declara el sistema'}
              </span>
            )}
            {admin && (
              <span className="ml-auto flex items-center gap-2">
                {detail.status === 'active' ? (
                  <Button size="sm" variant="outline" disabled={setActive.isPending} onClick={() => setActive.mutate(null, { onSuccess: () => toast.success('Medición fuera de uso.') })}>
                    Dejar de usar
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    disabled={setActive.isPending}
                    title="Un dato que el sistema suele leer mal irá a revisión aunque diga estar seguro, desde los próximos documentos."
                    onClick={() =>
                      setActive.mutate(detail.version, {
                        onSuccess: () => toast.success('Medición en uso para los próximos documentos.'),
                        onError: (e) => toast.error(errorDetail(e)),
                      })
                    }
                  >
                    Usar en la cola de revisión
                  </Button>
                )}
                {detail.status === 'draft' && (
                  <DeleteButton
                    path={`/v1/calibration/${detail.version}`}
                    label="Eliminar"
                    question="Se eliminará para siempre esta medición, que nunca se usó."
                    onDone={() => setPicked(undefined)}
                  />
                )}
              </span>
            )}
          </div>

          {fewData && (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm">
              <CircleAlert className="size-4 shrink-0 text-amber-600" />
              <span className="flex-1">
                <strong>Pocos datos para conclusiones firmes:</strong> {total} comprobaciones, y se recomiendan al menos {detail.min_observations} por dato. Úsalo como
                orientación{detail.status !== 'active' && ', y mejor no lo pongas en uso todavía'}.
              </span>
              <Button size="sm" variant="outline" asChild>
                <Link to="/evaluation">
                  <FlaskConical className="size-4" /> Medir con más documentos
                </Link>
              </Button>
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-3">
            <Stat label="Acierto real" value={accuracy !== null ? `${Math.round(accuracy * 10)} de cada 10` : '—'} note={`datos leídos bien (${right} de ${total})`} />
            <Stat
              label="Lo que el sistema cree de sí mismo"
              value={pct(meanSaid)}
              tone={gap !== null && gap > 0.1 ? 'bad' : undefined}
              note={gap !== null && gap > 0.1 ? `Se sobreestima: dice ${pct(meanSaid)} y acierta ${pct(accuracy)}.` : 'En línea con lo que acierta.'}
            />
            <Stat
              label="Datos que una persona debe revisar siempre"
              value={`${detail.fields.filter((f) => levelOf(f.accuracy) === LEVELS[2]).length} de ${detail.fields.length}`}
              tone={detail.fields.some((f) => levelOf(f.accuracy) === LEVELS[2]) ? 'bad' : undefined}
              note="aciertan menos de 85 de cada 100 veces"
            />
          </div>

          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-semibold">¿En qué datos puedo confiar?</h2>
            <div className="grid items-start gap-3 md:grid-cols-3">
              {LEVELS.map((level) => {
                const fields = detail.fields.filter((f) => levelOf(f.accuracy) === level).sort((a, b) => a.accuracy - b.accuracy)
                return (
                  <div key={level.title} className={cn('flex flex-col gap-2 rounded-xl border border-t-4 bg-muted/40 p-3', level.band)}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className={cn('font-semibold', level.text)}>{level.title}</span>
                      <span className="text-sm text-muted-foreground">{fields.length}</span>
                    </div>
                    <span className="-mt-1 text-xs text-muted-foreground">{level.hint}</span>
                    {fields.length ? fields.map((f) => <FieldCard key={f.key} field={f} />) : <span className="py-2 text-xs text-muted-foreground">Ningún dato aquí.</span>}
                  </div>
                )
              })}
            </div>
          </section>

          <section className="flex flex-col gap-2 rounded-xl border bg-card p-4">
            <h2 className="font-semibold">¿Cuánto podría pasar sin revisión?</h2>
            {noneCanPass ? (
              <p className="text-sm">
                Con lo que acierta hoy, <strong>ningún dato debería pasar sin revisión</strong>, ni aceptando {errorsIn(Math.max(...suggestions.map((s) => s.target_error)))}.
              </p>
            ) : (
              <div className="flex flex-col text-sm">
                {suggestions.map((s) => (
                  <div key={s.target_error} className="flex flex-wrap items-baseline gap-x-2 border-b py-1.5 last:border-0">
                    <span className="min-w-56 text-muted-foreground">Aceptando {errorsIn(s.target_error)}:</span>
                    {s.threshold === null ? (
                      <span className="font-medium">ningún dato pasaría sin revisión.</span>
                    ) : (
                      <>
                        <span className="font-medium">{pct(s.coverage)} de los datos pasarían sin revisión</span>
                        <span className="text-xs text-muted-foreground">(confianza mínima en el perfil: {s.threshold.toFixed(2)})</span>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <details className="rounded-xl border p-3 text-sm">
            <summary className="cursor-pointer text-muted-foreground select-none">Detalle técnico</summary>
            <div className="mt-3 flex flex-col gap-2">
              <span className="text-xs text-muted-foreground">
                Medición v{detail.version} · {detail.report.observations.evaluation} observaciones de evaluación y {detail.report.observations.review} de revisión humana ·
                calculada por {detail.created_by} el {date(detail.created_at)}. ECE: diferencia promedio entre la confianza declarada y el acierto real. «Calibrada al
                100%»: la confianza que se usa cuando el sistema dice 100%.
              </span>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Campo</TableHead>
                    <TableHead>n</TableHead>
                    <TableHead>Acierto</TableHead>
                    <TableHead>Confianza media</TableHead>
                    <TableHead>ECE</TableHead>
                    <TableHead>Brier</TableHead>
                    <TableHead>Calibrada al 100%</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.fields.map((f) => (
                    <TableRow key={f.key}>
                      <TableCell>
                        <code className="text-xs">{f.key}</code>
                      </TableCell>
                      <TableCell>{f.count}</TableCell>
                      <TableCell>{pct(f.accuracy)}</TableCell>
                      <TableCell>{pct(f.mean_confidence)}</TableCell>
                      <TableCell>{pct(f.ece)}</TableCell>
                      <TableCell>{f.brier ?? '—'}</TableCell>
                      <TableCell>{pct(f.bins[f.bins.length - 1]?.calibrated)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </details>
        </>
      )}
    </div>
  )
}
