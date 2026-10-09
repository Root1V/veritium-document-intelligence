// One evaluation suite (VRT-42): its cases, its runs, and a run's metrics
// compared with the previous completed run — what got better and what
// broke, field by field.
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CheckCircle2, CircleX, Loader2, Play } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute, isAISpecialist } from '@/lib/auth'
import { configChanges, percent, show } from '@/lib/evaluation'
import { humanizeFieldName } from '@/lib/extraction'
import { useDocumentTypeCatalog, useEvalRun, useEvalSuite, usePrompts, useRunEvalSuite } from '@/lib/queries'
import type { EvalChange, EvalRunDetail, EvalRunSummary } from '@/types/api'

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col rounded-md border p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xl font-semibold">{value}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  )
}

function Changes({ title, changes, run, tone }: { title: string; changes: EvalChange[]; run: EvalRunDetail; tone: 'bad' | 'good' }) {
  const filename = (caseId: string) => run.results.find((r) => r.case_id === caseId)?.filename ?? caseId.slice(0, 8)
  return (
    <div className="flex flex-col gap-1">
      <span className={tone === 'bad' ? 'text-sm font-medium text-destructive' : 'text-sm font-medium text-emerald-700 dark:text-emerald-400'}>
        {title} ({changes.length})
      </span>
      {changes.length === 0 && <span className="text-xs text-muted-foreground">Ninguna.</span>}
      {changes.map((c, i) => (
        <span key={i} className="text-xs">
          {filename(c.case_id)} · <span className="font-medium">{c.field === 'tipo' ? 'tipo de documento' : humanizeFieldName(c.field)}</span>: esperado{' '}
          <code>{show(c.expected)}</code>, antes <code>{show(c.before)}</code>, ahora <code>{show(c.after)}</code>
        </span>
      ))}
    </div>
  )
}

function RunView({ runId, baseline }: { runId: string; baseline: EvalRunSummary | undefined }) {
  const { data: run, isLoading } = useEvalRun(runId, baseline?.id)
  const { data: types } = useDocumentTypeCatalog()
  const typeName = useMemo(() => Object.fromEntries((types?.registered ?? []).map((t) => [t.name, t.display_name])), [types])
  if (isLoading || !run) return <Loader2 className="size-5 animate-spin text-muted-foreground" />
  if (run.status === 'pending' || run.status === 'running')
    return (
      <span className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Corriendo: {run.results.length} de {run.case_count} casos.
      </span>
    )
  const m = run.metrics
  const fieldLabel = (key: string) => {
    const [type, ...field] = key.split('.')
    return `${typeName[type] ?? type} · ${humanizeFieldName(field.join('.'))}`
  }

  return (
    <div className="flex flex-col gap-4">
      {run.error && <span className="text-sm text-destructive">La corrida falló: {run.error}</span>}
      <Link to={`/prompts?eval_run=${run.id}`} className="w-fit text-xs underline">
        Instrucciones con que se hizo esta corrida
      </Link>
      {m && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="Clasificación" value={percent(m.classification)} />
          <Metric label="Campos" value={percent(m.fields)} />
          <Metric label="Casos" value={String(m.cases)} hint={m.failed ? `${m.failed} fallaron` : 'ninguno falló'} />
          <Metric label="Modelo de razonamiento" value={run.provenance?.models?.reasoning ?? '—'} hint={`visión: ${run.provenance?.models?.vision ?? '—'}`} />
        </div>
      )}

      {run.comparison && baseline && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Frente a la corrida del {new Date(baseline.created_at).toLocaleString()}</CardTitle>
            <CardDescription>
              Campos {percent(baseline.metrics?.fields)} → {percent(m?.fields)} · clasificación {percent(baseline.metrics?.classification)} →{' '}
              {percent(m?.classification)}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-1 pb-0 text-sm">
            <span className="font-medium">Qué cambió entre las dos corridas</span>
            {configChanges(baseline.provenance, run.provenance).map((c) => (
              <span key={c}>• {c}</span>
            ))}
            {configChanges(baseline.provenance, run.provenance).length === 0 && (
              <span className="text-muted-foreground">Nada de la configuración: la diferencia, si la hay, es variación del modelo.</span>
            )}
          </CardContent>
          <CardContent className="grid grid-cols-1 gap-4 pt-4 md:grid-cols-2">
            <Changes title="Regresiones" changes={run.comparison.regressions} run={run} tone="bad" />
            <Changes title="Mejoras" changes={run.comparison.improvements} run={run} tone="good" />
          </CardContent>
        </Card>
      )}

      {m && Object.keys(m.by_field).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Exactitud por campo</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Campo</TableHead>
                  <TableHead>Exactitud</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(m.by_field).map(([key, rate]) => (
                  <TableRow key={key}>
                    <TableCell className="text-sm">{fieldLabel(key)}</TableCell>
                    <TableCell className="text-sm">{percent(rate)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Casos</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          {run.results.map((r) => {
            const typeOk = !r.expected_document_type || r.expected_document_type === r.predicted_document_type
            const wrong = r.fields.filter((f) => !f.match)
            return (
              <div key={r.case_id} className="flex flex-col gap-1 rounded-md border p-2">
                <div className="flex flex-wrap items-center gap-2">
                  {r.status === 'failed' || !typeOk || wrong.length ? <CircleX className="size-4 text-destructive" /> : <CheckCircle2 className="size-4 text-emerald-600" />}
                  <span className="font-medium">{r.filename}</span>
                  <Badge variant={typeOk ? 'outline' : 'destructive'} className="text-[10px]">
                    {r.predicted_document_type ? (typeName[r.predicted_document_type] ?? r.predicted_document_type) : 'sin tipo'}
                    {!typeOk && ` (esperado ${typeName[r.expected_document_type ?? ''] ?? r.expected_document_type})`}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {r.fields.length - wrong.length}/{r.fields.length} campos
                    {r.duration_ms !== null && ` · ${(r.duration_ms / 1000).toFixed(1)} s`}
                  </span>
                </div>
                {r.error && <span className="text-xs text-destructive">{r.error}</span>}
                {wrong.map((f) => (
                  <span key={f.field} className="text-xs">
                    {humanizeFieldName(f.field)}: esperado <code>{show(f.expected)}</code>, extraído <code>{show(f.actual)}</code>
                    {f.confidence !== null && <span className="text-muted-foreground"> (confianza {Math.round(f.confidence * 100)}%)</span>}
                  </span>
                ))}
              </div>
            )
          })}
        </CardContent>
      </Card>
    </div>
  )
}

export function EvaluationSuitePage() {
  const { suiteId } = useParams<{ suiteId: string }>()
  const { data: suite, isLoading } = useEvalSuite(suiteId)
  const runSuite = useRunEvalSuite()
  const [selected, setSelected] = useState<string | null>(null)
  const [withMeaning, setWithMeaning] = useState(false)
  const { data: prompts } = usePrompts()
  const drafts = (prompts ?? []).filter((p) => p.draft)
  const [chosenDrafts, setChosenDrafts] = useState<string[]>([])
  if (isLoading || !suite) return <Loader2 className="size-6 animate-spin text-muted-foreground" />

  const runs = suite.runs
  const current = runs.find((r) => r.id === selected) ?? runs[0]
  // The baseline is the completed run just before the one shown.
  const baseline = current ? runs.slice(runs.indexOf(current) + 1).find((r) => r.status === 'completed') : undefined
  const busy = runs.some((r) => r.status === 'pending' || r.status === 'running')

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{suite.name}</h1>
          <p className="text-sm text-muted-foreground">
            {suite.description ?? ''} {suite.case_count} casos · {suite.source === 'corrections' ? 'desde correcciones' : 'desde tabla'} · creada por{' '}
            {suite.created_by}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {(canExecute() || isAISpecialist()) && (
            <Button
              disabled={busy || runSuite.isPending}
              onClick={() =>
                runSuite.mutate({ suiteId: suite.id, semanticGrounding: withMeaning || undefined, promptDrafts: chosenDrafts }, {
                  onSuccess: (r) => {
                    setSelected(r.id)
                    toast.success('Corrida en curso.')
                  },
                  onError: (e) => toast.error(errorDetail(e)),
                })
              }
            >
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} Correr con la configuración actual
            </Button>
          )}
          {(canExecute() || isAISpecialist()) && (
            <label className="flex items-center gap-2 text-sm" title="Le dice al modelo qué significa cada campo para el negocio, según el catálogo semántico.">
              <input type="checkbox" checked={withMeaning} onChange={(e) => setWithMeaning(e.target.checked)} />
              Probar con el significado de negocio de cada campo
            </label>
          )}
          {(canExecute() || isAISpecialist()) &&
            drafts.map((p) => (
              <label key={p.draft!.id} className="flex items-center gap-2 text-sm" title={`Motivo: ${p.draft!.reason}`}>
                <input
                  type="checkbox"
                  checked={chosenDrafts.includes(p.draft!.id)}
                  onChange={(e) => setChosenDrafts((c) => (e.target.checked ? [...c, p.draft!.id] : c.filter((id) => id !== p.draft!.id)))}
                />
                Probar con el borrador de «{p.label}»
              </label>
            ))}
          <Link to="/evaluation" className="text-sm underline">
            Volver
          </Link>
        </div>
      </div>

      {runs.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {runs.map((r) => (
            <Button key={r.id} size="sm" variant={r.id === current?.id ? 'default' : 'outline'} onClick={() => setSelected(r.id)}>
              {new Date(r.created_at).toLocaleString()} · {r.status === 'completed' ? percent(r.metrics?.fields) : r.status}
              {r.provenance?.semantic_grounding && ' · con significado'}
              {r.options?.prompt_drafts?.length ? ' · con borrador' : ''}
            </Button>
          ))}
        </div>
      )}

      {current ? <RunView runId={current.id} baseline={baseline} /> : <p className="text-sm text-muted-foreground">Todavía no se corrió.</p>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Lo que se espera</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Documento</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead>Valores esperados</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {suite.cases.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="text-sm">
                    {c.source_document_id ? (
                      <Link to={`/documents/${c.source_document_id}`} className="underline-offset-4 hover:underline">
                        {c.filename}
                      </Link>
                    ) : (
                      c.filename
                    )}
                    {c.page_start !== null && <span className="text-xs text-muted-foreground"> · pág. {c.page_start + 1}{c.page_end !== null && c.page_end !== c.page_start && `–${c.page_end + 1}`}</span>}
                  </TableCell>
                  <TableCell className="text-sm">{c.expected_document_type ?? '—'}</TableCell>
                  <TableCell className="text-xs">
                    {Object.entries(c.expected_fields)
                      .map(([k, v]) => `${humanizeFieldName(k)}: ${show(v)}`)
                      .join(' · ') || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
