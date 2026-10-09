// Field accuracy and confidence calibration (VRT-43): how often each field
// is actually right at the confidence the model reports, and — once an
// admin activates a version — the confidence review routing compares with
// the threshold.
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { errorDetail } from '@/lib/apiErrors'
import { isAdmin } from '@/lib/auth'
import { humanizeFieldName } from '@/lib/extraction'
import { useCalibration, useCalibrations, useComputeCalibration, useDocumentTypeCatalog, useSetActiveCalibration } from '@/lib/queries'

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`)
const STATUS = { active: 'activa', draft: 'borrador', retired: 'retirada' } as const

export function CalibrationPage() {
  const { data: versions, isLoading } = useCalibrations()
  const compute = useComputeCalibration()
  const setActive = useSetActiveCalibration()
  const [selected, setSelected] = useState<number | undefined>()
  const shown = selected ?? versions?.[0]?.version
  const { data: detail } = useCalibration(shown)
  const { data: types } = useDocumentTypeCatalog()
  const typeName = useMemo(() => Object.fromEntries((types?.registered ?? []).map((t) => [t.name, t.display_name])), [types])
  const label = (key: string) => {
    const [type, ...field] = key.split('.')
    return `${typeName[type] ?? type} · ${humanizeFieldName(field.join('.').replace('[]', ''))}`
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Calibración de confianza</h1>
          <p className="max-w-3xl text-muted-foreground">
            Qué tan seguido acierta cada campo con la confianza que reporta el modelo, medido con las{' '}
            <Link to="/evaluation" className="underline">
              suites de evaluación
            </Link>{' '}
            y las revisiones humanas. Con una versión activa, la cola de revisión decide con la confianza calibrada.
          </p>
        </div>
        {isAdmin() && (
          <Button
            disabled={compute.isPending}
            onClick={() =>
              compute.mutate(undefined, {
                onSuccess: (v) => {
                  setSelected(v.version)
                  toast.success(`Versión ${v.version} calculada como borrador.`)
                },
                onError: (e) => toast.error(errorDetail(e)),
              })
            }
          >
            {compute.isPending && <Loader2 className="size-4 animate-spin" />} Calcular con los datos actuales
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (versions ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">Todavía no hay calibraciones. Hoy la cola de revisión usa la confianza que reporta el modelo.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {(versions ?? []).map((v) => (
            <Button key={v.version} size="sm" variant={v.version === shown ? 'default' : 'outline'} onClick={() => setSelected(v.version)}>
              v{v.version} · {STATUS[v.status]}
            </Button>
          ))}
          {!(versions ?? []).some((v) => v.status === 'active') && <span className="text-xs text-muted-foreground">Ninguna activa: se usa la confianza del modelo.</span>}
        </div>
      )}

      {detail && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2">
                Versión {detail.version} <Badge variant={detail.status === 'active' ? 'default' : 'outline'}>{STATUS[detail.status]}</Badge>
              </CardTitle>
              <CardDescription>
                {detail.report.observations.evaluation} observaciones de evaluación y {detail.report.observations.review} de revisión humana · calculada por{' '}
                {detail.created_by} el {new Date(detail.created_at).toLocaleString()}
                {detail.activated_at && ` · activada por ${detail.activated_by} el ${new Date(detail.activated_at).toLocaleString()}`}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              <span className="font-medium">Umbral sugerido para el perfil (confianza calibrada mínima)</span>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Error tolerado</TableHead>
                    <TableHead>Umbral</TableHead>
                    <TableHead>Pasan sin revisión</TableHead>
                    <TableHead>Error observado entre ellos</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.report.suggestions.map((s) => (
                    <TableRow key={s.target_error}>
                      <TableCell>{pct(s.target_error)}</TableCell>
                      <TableCell>{s.threshold === null ? 'ninguno lo alcanza' : s.threshold.toFixed(2)}</TableCell>
                      <TableCell>{pct(s.coverage)}</TableCell>
                      <TableCell>{pct(s.error_rate)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <span className="text-xs text-muted-foreground">
                El umbral se fija en cada perfil de proceso («confianza mínima por campo»). Activar la calibración no lo cambia: cambia la confianza que se
                compara con él.
              </span>
              {isAdmin() && (
                <div>
                  {detail.status === 'active' ? (
                    <Button variant="outline" disabled={setActive.isPending} onClick={() => setActive.mutate(null, { onSuccess: () => toast.success('Calibración desactivada.') })}>
                      Desactivar
                    </Button>
                  ) : (
                    <Button
                      disabled={setActive.isPending}
                      onClick={() =>
                        setActive.mutate(detail.version, {
                          onSuccess: () => toast.success(`Versión ${detail.version} activa desde la próxima corrida.`),
                          onError: (e) => toast.error(errorDetail(e)),
                        })
                      }
                    >
                      Activar para la cola de revisión
                    </Button>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Por campo</CardTitle>
              <CardDescription>
                Con menos de {detail.min_observations} observaciones un campo es preliminar. ECE: cuánto se aleja la confianza del modelo de su acierto real.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Campo</TableHead>
                    <TableHead>Observaciones</TableHead>
                    <TableHead>Acierto real</TableHead>
                    <TableHead>Confianza del modelo</TableHead>
                    <TableHead>ECE</TableHead>
                    <TableHead>Si el modelo dice 100%</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.fields.map((f) => (
                    <TableRow key={f.key}>
                      <TableCell className="text-sm">{label(f.key)}</TableCell>
                      <TableCell className="text-sm">
                        {f.count} {f.preliminary && <Badge variant="outline" className="text-[10px]">preliminar</Badge>}
                      </TableCell>
                      <TableCell className="text-sm">{pct(f.accuracy)}</TableCell>
                      <TableCell className="text-sm">{pct(f.mean_confidence)}</TableCell>
                      <TableCell className={(f.ece ?? 0) > 0.1 ? 'text-sm text-destructive' : 'text-sm'}>{pct(f.ece)}</TableCell>
                      <TableCell className="text-sm">{pct(f.bins[f.bins.length - 1]?.calibrated)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
