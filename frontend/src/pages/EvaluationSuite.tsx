// One evaluation suite (VRT-42, VRT-107): its runs on the left, each with
// its result, and the chosen one beside them — a banner that says whether it
// got better or worse than the run before, what changed in between, what
// got better and what broke, the accuracy of each field, and each document.
// What is expected of each document and the models used stay folded.
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowRight, CheckCircle2, CircleX, Loader2, Play, TrendingDown, TrendingUp, Minus } from 'lucide-react'
import { RunDialog } from '@/components/evaluation/RunDialog'
import { Button } from '@/components/ui/button'
import { canExecute, isAISpecialist } from '@/lib/auth'
import { configChanges, percent, show, toneOf } from '@/lib/evaluation'
import { humanizeFieldName } from '@/lib/extraction'
import { useDocumentTypeCatalog, useEvalRun, useEvalSuite } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { EvalChange, EvalRate, EvalRunDetail, EvalRunSummary } from '@/types/api'

const when = (iso: string) => new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
const tried = (r: EvalRunSummary) =>
  [r.provenance?.semantic_grounding && 'con significado', r.provenance?.self_check && 'con autovalidación', r.options?.prompt_drafts?.length && 'con borrador'].filter(Boolean).join(' · ')

function Bar({ rate }: { rate: EvalRate | null | undefined }) {
  return (
    <span className="h-1.5 overflow-hidden rounded-full bg-muted">
      <span className={cn('block h-full rounded-full', toneOf(rate).bar)} style={{ width: `${Math.round((rate?.accuracy ?? 0) * 100)}%` }} />
    </span>
  )
}

function Stat({ label, rate }: { label: string; rate: EvalRate | null | undefined }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border bg-card p-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={cn('text-2xl font-semibold', toneOf(rate).text)}>{rate?.accuracy == null ? '—' : `${rate.correct} de ${rate.evaluated}`}</span>
      <Bar rate={rate} />
    </div>
  )
}

function Changes({ title, changes, run, tone, nameOf }: { title: string; changes: EvalChange[]; run: EvalRunDetail; tone: 'bad' | 'good'; nameOf: (type: string | null | undefined, field: string) => string }) {
  const filename = (caseId: string) => run.results.find((r) => r.case_id === caseId)?.filename ?? caseId.slice(0, 8)
  const typeOf = (caseId: string) => run.results.find((r) => r.case_id === caseId)?.expected_document_type
  return (
    <div className="flex flex-col gap-1.5">
      <span className={cn('text-sm font-medium', tone === 'bad' ? 'text-red-700 dark:text-red-400' : 'text-emerald-700 dark:text-emerald-400')}>
        {title} · {changes.length}
      </span>
      {changes.length === 0 && <span className="text-xs text-muted-foreground">Ninguna.</span>}
      {changes.map((c, i) => (
        <span key={i} className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="font-medium">{nameOf(typeOf(c.case_id), c.field)}</span>
          <span className="text-muted-foreground">en {filename(c.case_id)}:</span>
          <code className="rounded bg-muted px-1">{show(c.before)}</code>
          <ArrowRight className="size-3 text-muted-foreground" />
          <code className="rounded bg-muted px-1">{show(c.after)}</code>
          <span className="text-muted-foreground">(correcto: {show(c.expected)})</span>
        </span>
      ))}
    </div>
  )
}

function RunView({ runId, baseline }: { runId: string; baseline: EvalRunSummary | undefined }) {
  const { data: run, isLoading } = useEvalRun(runId, baseline?.id)
  const { data: types } = useDocumentTypeCatalog()
  const typeName = useMemo(() => Object.fromEntries((types?.registered ?? []).map((t) => [t.name, t.display_name])), [types])
  // The catalog's name for a field ("employee_code" → "Código de trabajador").
  const nameOf = (type: string | null | undefined, field: string) =>
    (field === 'tipo' ? 'Tipo de documento' : types?.registered.find((t) => t.name === type)?.fields.find((f) => f.name === field)?.label) ?? humanizeFieldName(field)
  if (isLoading || !run) return <Loader2 className="size-5 animate-spin text-muted-foreground" />
  if (run.status === 'pending' || run.status === 'running')
    return (
      <div className="flex items-center gap-2 rounded-xl border bg-card p-4 text-sm">
        <Loader2 className="size-4 animate-spin" /> Corriendo: {run.results.length} de {run.case_count} documentos.
      </div>
    )
  const m = run.metrics
  const before = baseline?.metrics?.fields?.accuracy
  const now = m?.fields?.accuracy
  const delta = before != null && now != null ? now - before : null
  const verdict =
    run.status === 'failed'
      ? { icon: CircleX, tone: 'border-red-500/40 bg-red-500/10 text-red-800 dark:text-red-300', text: `La corrida falló: ${run.error ?? 'sin detalle'}` }
      : delta === null
        ? { icon: Minus, tone: 'border-border bg-muted/40', text: 'Primera corrida: todavía no hay con qué comparar.' }
        : delta > 0.001
          ? { icon: TrendingUp, tone: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300', text: `Mejoró: ${percent(baseline!.metrics!.fields)} → ${percent(m!.fields)} de datos bien leídos.` }
          : delta < -0.001
            ? { icon: TrendingDown, tone: 'border-red-500/40 bg-red-500/10 text-red-800 dark:text-red-300', text: `Empeoró: ${percent(baseline!.metrics!.fields)} → ${percent(m!.fields)} de datos bien leídos.` }
            : { icon: Minus, tone: 'border-border bg-muted/40', text: `Igual que la anterior: ${percent(m!.fields)} de datos bien leídos.` }
  const changes = baseline ? configChanges(baseline.provenance, run.provenance) : []
  const promptChanges = changes.filter((c) => c.startsWith('Cambiaron las instrucciones')).length
  const others = changes.filter((c) => !c.startsWith('Cambiaron las instrucciones'))
  const summary = [promptChanges && (promptChanges === 1 ? '1 instrucción al modelo' : `${promptChanges} instrucciones al modelo`), ...others.map((c) => c.toLowerCase())]
    .filter(Boolean)
    .join(', ')
  const fieldLabel = (key: string) => {
    const [type, ...field] = key.split('.')
    return { type: typeName[type] ?? type, field: nameOf(type, field.join('.')) }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className={cn('flex items-start gap-2 rounded-xl border px-4 py-3 text-sm', verdict.tone)}>
        <verdict.icon className="mt-0.5 size-4 shrink-0" />
        <span className="flex-1">
          <span className="font-medium">{verdict.text}</span>
          {baseline && (
            <span className="block text-xs opacity-80">
              Frente a la corrida del {when(baseline.created_at)} ·{' '}
              {changes.length ? `Entre una y otra cambió la configuración: ${summary}.` : 'Sin cambios de configuración entre una y otra: la diferencia, si la hay, es variación del modelo.'}
            </span>
          )}
          {changes.length > 0 && (
            <details className="mt-1 text-xs opacity-80">
              <summary className="cursor-pointer select-none">Ver qué cambió</summary>
              <ul className="mt-1 list-disc pl-4">
                {changes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </details>
          )}
        </span>
      </div>

      {m && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="Datos leídos bien" rate={m.fields} />
          <Stat label="Tipo de documento reconocido" rate={m.classification} />
          <div className="flex flex-col gap-1 rounded-xl border bg-card p-4">
            <span className="text-sm text-muted-foreground">Documentos</span>
            <span className="text-2xl font-semibold">{m.cases}</span>
            <span className={cn('text-xs', m.failed ? 'text-red-700 dark:text-red-400' : 'text-muted-foreground')}>{m.failed ? `${m.failed} no se pudieron procesar` : 'todos se procesaron'}</span>
          </div>
        </div>
      )}

      {run.comparison && baseline && (run.comparison.regressions.length > 0 || run.comparison.improvements.length > 0) && (
        <div className="grid gap-4 rounded-xl border bg-card p-4 md:grid-cols-2">
          <Changes title="Empeoró" changes={run.comparison.regressions} run={run} tone="bad" nameOf={nameOf} />
          <Changes title="Mejoró" changes={run.comparison.improvements} run={run} tone="good" nameOf={nameOf} />
        </div>
      )}

      {m && Object.keys(m.by_field).length > 0 && (
        <section className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <h3 className="font-semibold">Cada dato</h3>
          <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {Object.entries(m.by_field)
              .sort(([, a], [, b]) => (a.accuracy ?? 0) - (b.accuracy ?? 0))
              .map(([key, rate]) => {
                const { type, field } = fieldLabel(key)
                return (
                  <div key={key} className="flex flex-col gap-1">
                    <span className="flex items-baseline justify-between gap-2 text-sm">
                      <span>
                        {field} <span className="text-xs text-muted-foreground">· {type}</span>
                      </span>
                      <span className={cn('text-xs font-semibold', toneOf(rate).text)}>
                        {rate.correct} de {rate.evaluated}
                      </span>
                    </span>
                    <Bar rate={rate} />
                  </div>
                )
              })}
          </div>
        </section>
      )}

      <section className="flex flex-col rounded-xl border bg-card">
        <h3 className="border-b px-4 py-2.5 font-semibold">Cada documento</h3>
        {run.results.map((r) => {
          const typeOk = !r.expected_document_type || r.expected_document_type === r.predicted_document_type
          const wrong = r.fields.filter((f) => !f.match)
          const ok = r.status !== 'failed' && typeOk && !wrong.length
          return (
            <div key={r.case_id} className="flex items-start gap-2.5 border-b px-4 py-2.5 last:border-0">
              {ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-red-600" />}
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="font-medium">{r.filename}</span>
                  <span className="text-xs text-muted-foreground">
                    {r.predicted_document_type ? (typeName[r.predicted_document_type] ?? r.predicted_document_type) : 'sin tipo'} · {r.fields.length - wrong.length} de {r.fields.length} datos
                    {r.duration_ms !== null && ` · ${Math.round(r.duration_ms / 1000)} s`}
                  </span>
                </span>
                {!typeOk && (
                  <span className="text-xs text-red-700 dark:text-red-400">Se reconoció como otro tipo: se esperaba {typeName[r.expected_document_type ?? ''] ?? r.expected_document_type}.</span>
                )}
                {r.error && <span className="text-xs text-red-700 dark:text-red-400">No se pudo procesar: {r.error}</span>}
                {wrong.map((f) => (
                  <span key={f.field} className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="text-muted-foreground">{nameOf(r.expected_document_type ?? r.predicted_document_type, f.field)}:</span>
                    <span>leyó</span>
                    <code className="rounded bg-red-500/10 px-1">{show(f.actual)}</code>
                    <span>y era</span>
                    <code className="rounded bg-emerald-500/10 px-1">{show(f.expected)}</code>
                  </span>
                ))}
              </div>
            </div>
          )
        })}
      </section>

      <details className="rounded-xl border px-4 py-3 text-sm">
        <summary className="cursor-pointer text-muted-foreground select-none">Con qué se hizo esta corrida</summary>
        <div className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
          <span>
            Modelo de razonamiento: {run.provenance?.models?.reasoning ?? '—'} · de visión: {run.provenance?.models?.vision ?? '—'}
          </span>
          <span>
            Corrida por {run.created_by} el {when(run.created_at)}
            {run.provenance?.code_version && ` · código ${run.provenance.code_version.slice(0, 7)}`}
          </span>
          <Link to={`/prompts?eval_run=${run.id}`} className="w-fit text-primary hover:underline">
            Ver las instrucciones al modelo con que se hizo
          </Link>
        </div>
      </details>
    </div>
  )
}

export function EvaluationSuitePage() {
  const { suiteId } = useParams<{ suiteId: string }>()
  const { data: suite, isLoading } = useEvalSuite(suiteId)
  const [selected, setSelected] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  if (isLoading || !suite) return <Loader2 className="size-6 animate-spin text-muted-foreground" />

  const runs = suite.runs
  const current = runs.find((r) => r.id === selected) ?? runs[0]
  // The baseline is the completed run just before the one shown.
  const baseline = current ? runs.slice(runs.indexOf(current) + 1).find((r) => r.status === 'completed') : undefined
  const busy = runs.some((r) => r.status === 'pending' || r.status === 'running')
  const may = canExecute() || isAISpecialist()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">{suite.name}</h1>
          <p className="text-sm text-muted-foreground">
            {suite.description ? `${suite.description} · ` : ''}
            {suite.case_count} documentos · {suite.source === 'corrections' ? 'desde las correcciones' : 'desde una tabla'} · creado por {suite.created_by}
          </p>
        </div>
        {may && (
          <Button disabled={busy} onClick={() => setRunning(true)}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} {busy ? 'Corriendo…' : 'Correr'}
          </Button>
        )}
      </div>

      {!runs.length ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-10 text-center text-sm text-muted-foreground">
          Todavía no se corrió. Al correrlo verás cuántos datos lee bien y qué documentos fallan.
          {may && (
            <Button onClick={() => setRunning(true)}>
              <Play className="size-4" /> Correr ahora
            </Button>
          )}
        </div>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,18rem)_1fr]">
          <aside className="flex flex-col overflow-hidden rounded-xl border bg-card lg:sticky lg:top-16">
            <span className="border-b px-4 py-2 text-xs font-medium text-muted-foreground">Corridas</span>
            {runs.map((r) => {
              const active = r.id === current?.id
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setSelected(r.id)}
                  className={cn('flex flex-col gap-1 border-b px-4 py-2.5 text-left transition last:border-0 hover:bg-muted/50', active && 'bg-primary/5 shadow-[inset_3px_0_0] shadow-primary')}
                >
                  <span className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="font-medium">{new Date(r.created_at).toLocaleDateString('es-PE', { day: 'numeric', month: 'short' })}</span>
                    {r.status === 'completed' ? (
                      <span className={cn('text-xs font-semibold', toneOf(r.metrics?.fields).text)}>{percent(r.metrics?.fields).split(' ')[0]}</span>
                    ) : (
                      <span className={cn('text-xs', r.status === 'failed' ? 'text-red-700 dark:text-red-400' : 'text-muted-foreground')}>
                        {r.status === 'failed' ? 'falló' : 'corriendo'}
                      </span>
                    )}
                  </span>
                  {r.status === 'completed' && <Bar rate={r.metrics?.fields} />}
                  <span className="text-xs text-muted-foreground">
                    {new Date(r.created_at).toLocaleTimeString('es-PE', { hour: 'numeric', minute: '2-digit' })} · {r.created_by}
                    {tried(r) && ` · ${tried(r)}`}
                  </span>
                </button>
              )
            })}
          </aside>
          {current && <RunView runId={current.id} baseline={baseline} />}
        </div>
      )}

      <details className="rounded-xl border px-4 py-3 text-sm">
        <summary className="cursor-pointer text-muted-foreground select-none">Lo que se espera de cada documento ({suite.cases.length})</summary>
        <div className="mt-3 flex flex-col divide-y">
          {suite.cases.map((c) => (
            <div key={c.id} className="flex flex-col gap-0.5 py-2">
              <span className="text-sm">
                {c.source_document_id ? (
                  <Link to={`/documents/${c.source_document_id}`} className="font-medium hover:underline">
                    {c.filename}
                  </Link>
                ) : (
                  <span className="font-medium">{c.filename}</span>
                )}
                {c.page_start !== null && (
                  <span className="text-xs text-muted-foreground">
                    {' '}
                    · pág. {c.page_start + 1}
                    {c.page_end !== null && c.page_end !== c.page_start && `–${c.page_end + 1}`}
                  </span>
                )}
                <span className="text-xs text-muted-foreground"> · {c.expected_document_type ?? 'sin tipo'}</span>
              </span>
              <span className="text-xs text-muted-foreground">
                {Object.entries(c.expected_fields)
                  .map(([k, v]) => `${humanizeFieldName(k)}: ${show(v)}`)
                  .join(' · ') || 'Solo el tipo de documento.'}
              </span>
            </div>
          ))}
        </div>
      </details>

      {running && <RunDialog suiteId={suite.id} onClose={() => setRunning(false)} onStarted={(r) => (setSelected(r.id), setRunning(false))} />}
    </div>
  )
}
