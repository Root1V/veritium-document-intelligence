// How reliable the automatic reading is, data by data (VRT-43), told for an
// operator or an executive: which data can pass alone, which should always
// be checked by a person, and how much work that would save. The
// statistics behind it (ECE, Brier, bins) stay in a collapsed section.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CircleAlert, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { errorDetail } from '@/lib/apiErrors'
import { isAdmin } from '@/lib/auth'
import { cn } from '@/lib/utils'
import { useCalibration, useCalibrations, useComputeCalibration, useSetActiveCalibration } from '@/lib/queries'
import type { CalibrationDetail, CalibrationSummary } from '@/types/api'

type Field = CalibrationDetail['fields'][number]

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`)
const date = (iso: string) => new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })

// The traffic light: how often the data is actually right.
const LEVELS = [
  { min: 0.95, label: 'Confiable', advice: 'Puede pasar sin revisión.', dot: 'bg-emerald-500', badge: 'border-emerald-600 text-emerald-700 dark:text-emerald-400' },
  { min: 0.85, label: 'Con cuidado', advice: 'Conviene revisarlo cuando el documento es dudoso.', dot: 'bg-amber-500', badge: 'border-amber-600 text-amber-700 dark:text-amber-400' },
  { min: 0, label: 'Revisar siempre', advice: 'Una persona debería revisarlo siempre.', dot: 'bg-red-500', badge: 'border-red-600 text-red-700 dark:text-red-400' },
] as const
const levelOf = (accuracy: number) => LEVELS.find((l) => accuracy >= l.min) ?? LEVELS[2]

function errorsIn(target: number): string {
  return `1 error cada ${Math.round(1 / target)} datos`
}

function FieldRow({ field }: { field: Field }) {
  const level = levelOf(field.accuracy)
  const right = Math.round(field.accuracy * field.count)
  const overconfident = field.mean_confidence !== null && field.mean_confidence - field.accuracy > 0.1
  return (
    <div className="flex flex-col gap-1.5 border-b py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn('size-2.5 rounded-full', level.dot)} />
        <span className="font-medium">{field.label}</span>
        <span className="text-sm text-muted-foreground">· {field.document_type_name}</span>
        <Badge variant="outline" className={cn('ml-auto', level.badge)}>
          {level.label}
        </Badge>
      </div>
      <div className="h-2 w-full max-w-md overflow-hidden rounded-full bg-muted">
        <div className={cn('h-full', level.dot)} style={{ width: `${Math.round(field.accuracy * 100)}%` }} />
      </div>
      <p className="text-sm">
        Acertó <strong>{right} de {field.count}</strong> veces ({pct(field.accuracy)})
        {field.mean_confidence !== null &&
          (overconfident ? (
            <>
              , aunque el sistema decía estar seguro al <strong>{pct(field.mean_confidence)}</strong>.
            </>
          ) : (
            <>, y el sistema lo sabía: decía estar seguro al {pct(field.mean_confidence)}.</>
          ))}{' '}
        {level.advice}
      </p>
      {field.preliminary && <span className="text-xs text-muted-foreground">Orientativo: pocas comprobaciones todavía.</span>}
    </div>
  )
}

function Measurements({ versions, shown, onPick }: { versions: CalibrationSummary[]; shown: number | undefined; onPick: (v: number) => void }) {
  if (versions.length < 2) return null
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">Mediciones:</span>
      {versions.map((v) => (
        <Button key={v.version} size="sm" variant={v.version === shown ? 'secondary' : 'ghost'} onClick={() => onPick(v.version)}>
          {date(v.created_at)}
          {v.status === 'active' && ' (en uso)'}
        </Button>
      ))}
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

  const total = detail ? detail.fields.reduce((n, f) => n + f.count, 0) : 0
  const right = detail ? detail.fields.reduce((n, f) => n + Math.round(f.accuracy * f.count), 0) : 0
  const said = detail?.fields.filter((f) => f.mean_confidence !== null) ?? []
  const meanSaid = said.length ? said.reduce((n, f) => n + (f.mean_confidence ?? 0) * f.count, 0) / said.reduce((n, f) => n + f.count, 0) : null
  const alwaysCheck = detail?.fields.filter((f) => levelOf(f.accuracy) === LEVELS[2]).length ?? 0
  const fewData = detail?.fields.some((f) => f.preliminary)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Confiabilidad de la lectura automática</h1>
          <p className="text-muted-foreground">
            Compara lo que el sistema leyó con lo que confirmaron personas, dato por dato. Te dice qué datos pueden pasar solos y cuáles conviene que
            revise alguien.
          </p>
        </div>
        {isAdmin() && (
          <Button
            variant="outline"
            disabled={compute.isPending}
            onClick={() =>
              compute.mutate(undefined, {
                onSuccess: (v) => {
                  setPicked(v.version)
                  toast.success('Medición actualizada con los datos de hoy.')
                },
                onError: (e) => toast.error(errorDetail(e)),
              })
            }
          >
            {compute.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} Actualizar medición
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : !detail ? (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            Todavía no hay mediciones. Para tener una, corre una{' '}
            <Link to="/evaluation" className="underline">
              suite de evaluación
            </Link>{' '}
            con documentos reales y luego pulsa «Actualizar medición».
          </CardContent>
        </Card>
      ) : (
        <>
          <Measurements versions={versions ?? []} shown={shown} onPick={setPicked} />

          {fewData && (
            <div className="flex items-start gap-2 rounded-md border border-amber-500/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
              <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
              <span>
                Hay pocos datos para sacar conclusiones firmes: <strong>{total} comprobaciones</strong> en total. Recomendamos al menos{' '}
                {detail.min_observations} por dato. Para tener más, corre una{' '}
                <Link to="/evaluation" className="underline">
                  suite de evaluación
                </Link>{' '}
                con 20 a 30 documentos reales de cada tipo.
              </span>
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <Card>
              <CardContent className="flex flex-col gap-1 py-4">
                <span className="text-sm text-muted-foreground">Acierto real</span>
                <span className="text-2xl font-semibold">{total ? `${Math.round((right / total) * 10)} de cada 10` : '—'}</span>
                <span className="text-xs text-muted-foreground">
                  datos leídos correctamente ({right} de {total})
                </span>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex flex-col gap-1 py-4">
                <span className="text-sm text-muted-foreground">Seguridad que declara el sistema</span>
                <span className="text-2xl font-semibold">{pct(meanSaid)}</span>
                <span className="text-xs text-muted-foreground">
                  {meanSaid !== null && total && meanSaid - right / total > 0.1 ? 'Dice estar más seguro de lo que acierta.' : 'En línea con lo que acierta.'}
                </span>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex flex-col gap-1 py-4">
                <span className="text-sm text-muted-foreground">Datos a revisar siempre</span>
                <span className="text-2xl font-semibold">
                  {alwaysCheck} de {detail.fields.length}
                </span>
                <span className="text-xs text-muted-foreground">aciertan menos de 85 de cada 100 veces</span>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>¿En qué datos puedo confiar?</CardTitle>
              <CardDescription>
                Verde: puede pasar solo. Ámbar: con cuidado. Rojo: que lo revise una persona siempre.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {[...detail.fields]
                .sort((a, b) => a.accuracy - b.accuracy)
                .map((f) => (
                  <FieldRow key={f.key} field={f} />
                ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>¿Cuánto podría pasar sin revisión?</CardTitle>
              <CardDescription>Según cuántos errores esté dispuesto a aceptar el proceso.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              {detail.report.suggestions.map((s) => (
                <div key={s.target_error} className="flex flex-wrap items-baseline gap-x-2 border-b py-2 last:border-0">
                  <span className="min-w-56">Si se acepta {errorsIn(s.target_error)}:</span>
                  {s.threshold === null ? (
                    <span className="font-medium">ningún dato debería pasar sin revisión.</span>
                  ) : (
                    <>
                      <span className="font-medium">{pct(s.coverage)} de los datos pasarían sin revisión.</span>
                      <span className="text-xs text-muted-foreground">(valor para el perfil: {s.threshold.toFixed(2)})</span>
                    </>
                  )}
                </div>
              ))}
              {detail.report.suggestions.some((s) => s.threshold !== null) && (
                <span className="text-xs text-muted-foreground">
                  Ese valor lo fija un administrador en cada perfil de proceso, en «confianza mínima por campo».
                </span>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Usar esta medición en la cola de revisión</CardTitle>
              <CardDescription>
                Cuando está en uso, un dato que el sistema suele leer mal va a revisión aunque el sistema diga estar seguro. Aplica a los documentos que se
                procesen desde ese momento.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap items-center gap-3 text-sm">
              {detail.status === 'active' ? (
                <span>
                  <Badge>En uso</Badge> desde el {detail.activated_at && date(detail.activated_at)}, activada por {detail.activated_by}.
                </span>
              ) : (
                <span className="text-muted-foreground">
                  {inUse ? `Hoy está en uso la medición del ${date(inUse.created_at)}.` : 'Hoy no hay ninguna en uso: se usa la seguridad que declara el sistema.'}
                </span>
              )}
              {isAdmin() &&
                (detail.status === 'active' ? (
                  <Button variant="outline" disabled={setActive.isPending} onClick={() => setActive.mutate(null, { onSuccess: () => toast.success('Medición fuera de uso.') })}>
                    Dejar de usar
                  </Button>
                ) : (
                  <Button
                    disabled={setActive.isPending}
                    onClick={() =>
                      setActive.mutate(detail.version, {
                        onSuccess: () => toast.success('Medición en uso para los próximos documentos.'),
                        onError: (e) => toast.error(errorDetail(e)),
                      })
                    }
                  >
                    Usar esta medición
                  </Button>
                ))}
            </CardContent>
          </Card>

          <details className="rounded-md border p-3 text-sm">
            <summary className="cursor-pointer text-muted-foreground">Detalle técnico</summary>
            <div className="mt-3 flex flex-col gap-2">
              <span className="text-xs text-muted-foreground">
                Medición v{detail.version} · {detail.report.observations.evaluation} observaciones de evaluación y {detail.report.observations.review} de
                revisión humana · calculada por {detail.created_by} el {date(detail.created_at)}. ECE: diferencia promedio entre la confianza declarada y el
                acierto real. «Calibrada al 100%»: la confianza que se usa cuando el sistema dice 100%.
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
