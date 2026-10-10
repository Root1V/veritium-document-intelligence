// The end-to-end view of a case (VRT-38): what to do next and why
// (verdict, conditions), what the case says (consolidated entities), and
// where each piece of it came from — every source, document and finding
// opens the evidence viewer on its page with its box. Each of them can be
// reprocessed on its own as a new run (VRT-40), and the result exported (VRT-41).
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CheckCircle2, CircleAlert, Download, Loader2, RefreshCw, Search } from 'lucide-react'
import { toast } from 'sonner'
import { InvestigationPanel } from '@/components/cases/InvestigationPanel'
import { LensesCard } from '@/components/cases/LensesCard'
import { ProgressFunnel } from '@/components/cases/ProgressFunnel'
import { EvidenceViewer } from '@/components/documents/EvidenceViewer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute, isAISpecialist } from '@/lib/auth'
import {
  downloadCaseResult,
  useCaseInvestigations,
  useCaseProgress,
  useCaseResult,
  useDocumentTypeCatalog,
  useInvestigate,
  useReprocessCase,
  useWaiveCondition,
  type CaseExportFormat,
} from '@/lib/queries'
import { VERDICT_LABEL, VERDICT_VARIANT } from '@/lib/verdict'
import type { CaseCondition, CaseResult, ReprocessScope } from '@/types/api'

interface Evidence {
  documentId: string
  page: number
  bbox: [number, number, number, number] | null
  label: string
}

const STATUS_LABEL = { consistent: 'coincide', conflict: 'conflicto', single_source: 'una fuente' } as const

function show(value: unknown): string {
  if (value === null || value === undefined) return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function ConditionRow({ caseId, condition }: { caseId: string; condition: CaseCondition }) {
  const waive = useWaiveCondition()
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(false)
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {condition.status === 'open' ? <CircleAlert className="size-4 text-amber-600" /> : <CheckCircle2 className="size-4 text-emerald-600" />}
        <span className="font-medium">{condition.label}</span>
        <Badge variant={condition.status === 'open' ? 'destructive' : 'secondary'}>{condition.status === 'open' ? 'falta' : condition.status === 'waived' ? 'dispensada' : 'cumplida'}</Badge>
        <span className="text-xs text-muted-foreground">
          {condition.kind === 'missing_evidence' ? `evidencia: ${(condition.attributes ?? []).join(', ')} (${condition.role})` : condition.document_type}
        </span>
        {condition.status === 'open' && canExecute() && !open && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setOpen(true)}>
            Dispensar
          </Button>
        )}
      </div>
      {condition.status === 'waived' && (
        <span className="text-xs text-muted-foreground">
          Dispensada por {condition.waived_by}: {condition.waived_reason}
        </span>
      )}
      {open && (
        <div className="flex gap-2">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Motivo (queda auditado)" className="h-8 text-xs" />
          <Button
            size="sm"
            disabled={reason.trim().length < 3 || waive.isPending}
            onClick={() =>
              waive.mutate(
                { caseId, conditionId: condition.id, reason },
                { onSuccess: () => toast.success('Requisito dispensado; el veredicto se recalculó.'), onError: (e) => toast.error(errorDetail(e)) },
              )
            }
          >
            Confirmar
          </Button>
        </div>
      )}
    </div>
  )
}

const RUN_STATUS: Record<string, string> = { queued: 'en espera', pending: 'en cola', running: 'en curso', completed: 'terminada', failed: 'con error' }

const SCOPE_LABEL: Record<ReprocessScope['kind'], string> = { case: 'expediente', document: 'documento', rule: 'regla', attribute: 'atributo' }

function runLabel(run: NonNullable<CaseResult['run']>): string {
  if (run.trigger === 'correction') return ' · re-evaluación por corrección'
  if (run.trigger === 'reprocess' && run.scope) return ` · reproceso de ${SCOPE_LABEL[run.scope.kind]} ${run.scope.rule_id ?? run.scope.attribute ?? ''}`.trimEnd()
  return ''
}

/** Starts a reprocess run for one scope; re-extraction asks first (it calls the model again). */
function ReprocessButton({ caseId, scope, label, busy }: { caseId: string; scope: ReprocessScope; label: string; busy: boolean }) {
  const reprocess = useReprocessCase()
  const [asking, setAsking] = useState(false)
  if (!canExecute()) return null
  const reextracts = scope.kind === 'case' || scope.kind === 'document'
  const start = () =>
    reprocess.mutate(
      { caseId, scope },
      {
        onSuccess: (run) => {
          setAsking(false)
          toast.success(`Corrida ${run.run_number} en curso.`)
        },
        onError: (e) => toast.error(errorDetail(e)),
      },
    )
  if (asking)
    return (
      <span className="flex items-center gap-1 text-xs">
        Se vuelve a extraer con el modelo; las correcciones se conservan.
        <Button size="sm" className="h-6 px-2 text-xs" disabled={reprocess.isPending} onClick={start}>
          Confirmar
        </Button>
        <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => setAsking(false)}>
          Cancelar
        </Button>
      </span>
    )
  return (
    <Button
      size="sm"
      variant="ghost"
      className="h-6 px-2 text-xs"
      disabled={busy || reprocess.isPending}
      title={busy ? 'Hay una corrida en curso' : undefined}
      onClick={() => (reextracts ? setAsking(true) : start())}
    >
      <RefreshCw className="size-3" />
      {label}
    </Button>
  )
}

const EXPORTS: { format: CaseExportFormat; label: string }[] = [
  { format: 'pdf', label: 'PDF' },
  { format: 'markdown', label: 'Markdown' },
  { format: 'yaml', label: 'YAML' },
  { format: 'json', label: 'JSON' },
]

function ExportMenu({ caseId }: { caseId: string }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="ghost" className="h-6 px-2 text-xs">
          <Download className="size-3" />
          Exportar
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {EXPORTS.map((e) => (
          <DropdownMenuItem key={e.format} onSelect={() => downloadCaseResult(caseId, e.format).catch((err) => toast.error(errorDetail(err)))}>
            {e.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Where a field of a document's extraction is: its envelope's page and box. */
function fieldEvidence(result: CaseResult, documentId: string, fieldPath: string | null): Evidence | null {
  const doc = result.documents.find((d) => d.id === documentId)
  if (!doc) return null
  const first = fieldPath?.split(',')[0]?.split('+')[0]
  const envelope = first ? (doc.fields?.[first] as { page?: number | null; bbox?: [number, number, number, number] | null } | undefined) : undefined
  return { documentId, page: envelope?.page ?? doc.page_start ?? 0, bbox: envelope?.bbox ?? null, label: first ? `${doc.filename} · ${first}` : doc.filename }
}

export function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { data: result, isLoading } = useCaseResult(caseId)
  const { data: investigations } = useCaseInvestigations(caseId)
  const investigate = useInvestigate(caseId ?? '')
  const { data: summary } = useCaseProgress(caseId)
  const { data: types } = useDocumentTypeCatalog()
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const viewerRef = useRef<HTMLDivElement>(null)
  // Below the xl breakpoint the viewer sits under the content: bring it into view when evidence is chosen.
  useEffect(() => {
    if (evidence && !window.matchMedia('(min-width: 1280px)').matches) viewerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [evidence])
  const typeName = useMemo(() => Object.fromEntries((types?.registered ?? []).map((t) => [t.name, t.display_name])), [types])

  if (isLoading || !result) return <Loader2 className="size-6 animate-spin text-muted-foreground" />

  const decision = result.verdict.decision
  // A cross-document finding is reported once per document involved: same message, shown once with a count.
  const reasons = Object.values(
    result.verdict.reasons.reduce<Record<string, { decision: (typeof result.verdict.reasons)[number]['decision']; message: string; count: number }>>((acc, r) => {
      const k = `${r.decision}|${r.message}`
      acc[k] = { decision: r.decision, message: r.message, count: (acc[k]?.count ?? 0) + 1 }
      return acc
    }, {}),
  )
  const docName = (id: string | null) => {
    const d = result.documents.find((x) => x.id === id)
    return d ? `${d.document_type ? (typeName[d.document_type] ?? d.document_type) : 'Sin clasificar'} — ${d.filename}` : '—'
  }
  const busy = result.run?.status === 'pending' || result.run?.status === 'running'
  const investigationOf = Object.fromEntries((investigations ?? []).filter((i) => i.validation_issue_id).map((i) => [i.validation_issue_id!, i]))
  const investigating = (investigations ?? []).some((i) => i.status === 'running')
  const canInvestigate = canExecute() || isAISpecialist()
  const segmented = new Set(result.documents.map((d) => d.parent_document_id).filter(Boolean))
  const selected = evidence ?? (result.documents[0] ? { documentId: result.documents[0].id, page: result.documents[0].page_start ?? 0, bbox: null, label: result.documents[0].filename } : null)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{result.case.external_ref ?? result.case.id.slice(0, 8)}</h1>
        {decision && <Badge variant={VERDICT_VARIANT[decision]}>{VERDICT_LABEL[decision]}</Badge>}
        <Badge variant="outline">{summary?.progress.status_label ?? result.case.status}</Badge>
        <span className="text-xs text-muted-foreground">
          {result.case.profile ? `perfil ${result.case.profile.key} v${result.case.profile.version} · catálogo v${result.case.profile.semantic_catalog_version}` : 'sin perfil'} · canal {result.case.channel}
          {result.run && ` · corrida ${result.run.run_number} (${RUN_STATUS[result.run.status] ?? result.run.status})${runLabel(result.run)}`}
        </span>
        <ReprocessButton caseId={result.case.id} scope={{ kind: 'case' }} label="Reprocesar expediente" busy={busy} />
        <ExportMenu caseId={result.case.id} />
        {result.run && (
          <Link to={`/prompts?case=${result.case.id}`} className="text-xs underline">
            instrucciones usadas
          </Link>
        )}
        <Link to={`/asistente?case=${result.case.id}`} className="ml-auto text-sm underline">
          Preguntar al asistente
        </Link>
        <Link to="/cases" className="text-sm underline">
          Volver a expedientes
        </Link>
      </div>

      {summary && (
        <Card>
          <CardContent className="py-4">
            <ProgressFunnel progress={summary.progress} />
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,560px)]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Veredicto: {decision ? VERDICT_LABEL[decision] : 'pendiente'}</CardTitle>
              <CardDescription>Qué debe hacer el proceso y por qué.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-1 text-sm">
              {reasons.length === 0 && <span className="text-muted-foreground">Sin observaciones.</span>}
              {reasons.map((r) => (
                <div key={`${r.decision}|${r.message}`} className="flex items-start gap-2">
                  <Badge variant={VERDICT_VARIANT[r.decision]} className="shrink-0 text-[10px]">
                    {VERDICT_LABEL[r.decision]}
                  </Badge>
                  <span>
                    {r.message}
                    {r.count > 1 && <span className="text-muted-foreground"> (×{r.count})</span>}
                  </span>
                </div>
              ))}
              {result.run?.error && <span className="text-destructive">Error de la corrida: {result.run.error}</span>}
            </CardContent>
          </Card>

          {result.conditions.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Requisitos del perfil</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {result.conditions.map((c) => (
                  <ConditionRow key={c.id} caseId={result.case.id} condition={c} />
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Lo que dice el expediente</CardTitle>
              <CardDescription>Cada atributo consolidado entre documentos; haz clic en una fuente para ver de dónde sale.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {Object.keys(result.entities).length === 0 && <span className="text-sm text-muted-foreground">Sin atributos del catálogo semántico en este expediente.</span>}
              {Object.entries(result.entities).map(([role, entities]) => (
                <div key={role} className="flex flex-col gap-1">
                  <span className="text-sm font-semibold capitalize">{role}</span>
                  {Object.values(entities).flatMap((attrs) =>
                    Object.values(attrs).map((a) => (
                      <div key={`${role}.${a.attribute}`} className="flex flex-wrap items-center gap-2 border-b py-1.5 text-sm last:border-0">
                        <code className="min-w-48 text-xs">{a.attribute}</code>
                        <span className="font-medium">{show(a.value)}</span>
                        <Badge variant={a.status === 'conflict' ? 'destructive' : 'outline'} className="text-[10px]">
                          {STATUS_LABEL[a.status]}
                        </Badge>
                        {a.status === 'conflict' && <span className="text-xs text-destructive">valores: {a.distinct_values.map(show).join(' / ')}</span>}
                        <ReprocessButton caseId={result.case.id} scope={{ kind: 'attribute', attribute: a.attribute }} label="Re-evaluar" busy={busy} />
                        <span className="flex flex-wrap gap-1">
                          {a.sources.map((s, i) => (
                            <Button
                              key={i}
                              size="sm"
                              variant="ghost"
                              className="h-6 px-2 text-xs"
                              onClick={() => setEvidence({ documentId: s.document_id, page: s.page ?? 0, bbox: s.bbox, label: `${s.document_type} · ${s.field_path}` })}
                            >
                              {typeName[s.document_type] ?? s.document_type}
                              {s.page !== null && ` p.${s.page + 1}`}
                            </Button>
                          ))}
                        </span>
                      </div>
                    )),
                  )}
                </div>
              ))}
            </CardContent>
          </Card>

          <LensesCard caseId={result.case.id} onEvidence={(e) => setEvidence({ documentId: e.document_id, page: e.page, bbox: e.bbox, label: `${e.document_name} · pág. ${e.page + 1}` })} />

          {result.findings.length > 0 && (
            <Card>
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
                <div>
                  <CardTitle>Hallazgos ({result.findings.length})</CardTitle>
                  <CardDescription>Un agente puede investigar cada uno y dejarte un diagnóstico con evidencia; no decide por ti.</CardDescription>
                </div>
                {canInvestigate && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={investigate.isPending || investigating}
                    onClick={() => investigate.mutate(undefined, { onError: (e) => toast.error(errorDetail(e)) })}
                  >
                    {investigating ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />} Investigar hallazgos
                  </Button>
                )}
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                {result.findings.map((f, i) => (
                  <div key={i} className="flex flex-col gap-2 rounded-md border p-2">
                    <div className="flex items-start gap-2 hover:bg-muted/50">
                    <button
                      type="button"
                      className="flex flex-1 flex-col items-start gap-0.5 text-left"
                      onClick={() => f.document_id && setEvidence(fieldEvidence(result, f.document_id, f.field_path))}
                    >
                      <span className="flex items-center gap-2">
                        <Badge variant={f.severity === 'error' ? 'destructive' : 'outline'} className="text-[10px]">
                          {f.severity}
                        </Badge>
                        <code className="text-xs">{f.rule_id}</code>
                      </span>
                      <span className="whitespace-pre-line">{f.message}</span>
                      {f.document_id && <span className="text-xs text-muted-foreground">{docName(f.document_id)}</span>}
                    </button>
                    <ReprocessButton caseId={result.case.id} scope={{ kind: 'rule', rule_id: f.rule_id }} label="Re-evaluar regla" busy={busy} />
                    {canInvestigate && !investigationOf[f.id] && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={investigate.isPending}
                        onClick={() => investigate.mutate(f.id, { onError: (e) => toast.error(errorDetail(e)) })}
                      >
                        Investigar
                      </Button>
                    )}
                    </div>
                    {investigationOf[f.id] && (
                      <InvestigationPanel
                        investigation={investigationOf[f.id]}
                        onRetry={canInvestigate ? () => investigate.mutate(f.id, { onError: (e) => toast.error(errorDetail(e)) }) : undefined}
                        onEvidence={(documentId, page) => setEvidence({ documentId, page, bbox: null, label: `${docName(documentId)} · pág. ${page + 1}` })}
                      />
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Documentos ({result.documents.length})</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-1 text-sm">
              {result.documents.map((d) => (
                <div key={d.id} className="flex flex-wrap items-center gap-2 rounded-md p-1.5 hover:bg-muted/50">
                  <button
                    type="button"
                    className="flex flex-wrap items-center gap-2 text-left"
                    onClick={() => setEvidence({ documentId: d.id, page: d.page_start ?? 0, bbox: null, label: d.filename })}
                  >
                    <span className="font-medium">{d.document_type ? (typeName[d.document_type] ?? d.document_type) : 'Sin clasificar'}</span>
                    <span className="text-xs text-muted-foreground">{d.filename}</span>
                    <Badge variant="outline" className="text-[10px]">
                      {d.status}
                    </Badge>
                    {d.needs_review && <Badge variant="destructive" className="text-[10px]">revisión</Badge>}
                  </button>
                  <span className="ml-auto flex items-center gap-2">
                    {!d.parent_document_id && !segmented.has(d.id) && (
                      <ReprocessButton caseId={result.case.id} scope={{ kind: 'document', document_id: d.id }} label="Re-extraer" busy={busy} />
                    )}
                    <Link to={`/documents/${d.id}`} className="text-xs underline">
                      campos
                    </Link>
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="min-w-0" ref={viewerRef}>
          <div className="sticky top-4 flex flex-col gap-2">
            {selected ? (
              <>
                <span className="text-xs text-muted-foreground">{evidence ? evidence.label : docName(selected.documentId)}</span>
                <EvidenceViewer
                  key={selected.documentId}
                  documentId={selected.documentId}
                  page={selected.page}
                  onPageChange={(page) => setEvidence({ ...selected, page, bbox: null })}
                  highlights={selected.bbox ? [{ bbox: selected.bbox, active: true }] : []}
                  maxWidth={560}
                />
              </>
            ) : (
              <span className="text-sm text-muted-foreground">Sin documentos.</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
