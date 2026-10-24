// The end-to-end view of a case (VRT-38): what to do next and why
// (verdict, conditions), what the case says (consolidated entities), and
// where each piece of it came from — every source, document and finding
// opens the evidence viewer on its page with its box. Each of them can be
// reprocessed on its own as a new run (VRT-40), and the result exported (VRT-41).
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Bot, CheckCircle2, ChevronLeft, CircleAlert, CircleX, Download, Loader2, MessageSquareText, MoreHorizontal, RefreshCw, Search, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { InvestigationPanel } from '@/components/cases/InvestigationPanel'
import { LensesCard } from '@/components/cases/LensesCard'
import { ProgressFunnel } from '@/components/cases/ProgressFunnel'
import { EvidenceViewer } from '@/components/documents/EvidenceViewer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute, isAISpecialist, isAdmin } from '@/lib/auth'
import { DeleteButton, useDeleteAction } from '@/components/DeleteButton'
import { cn } from '@/lib/utils'
import { StatusBadge } from '@/components/StatusBadge'
import { DELETE_CASE } from '@/pages/Cases'
import {
  downloadCaseResult,
  useCaseInvestigations,
  useCaseProgress,
  useCaseResult,
  useDocumentTypeCatalog,
  useInvestigate,
  useProcessProfiles,
  useReprocessCase,
  useWaiveCondition,
  type CaseExportFormat,
} from '@/lib/queries'
import type { CaseCondition, CaseResult, ReprocessScope } from '@/types/api'
import { PersonalDataBar } from '@/components/cases/PersonalDataBar'

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

/** The decision first, as a traffic light, with why and what to do next (VRT-75). */
function VerdictBanner({
  decision,
  busy,
  reasons,
  runError,
}: {
  decision: CaseResult['verdict']['decision'] | null
  busy: boolean
  reasons: { decision: CaseResult['verdict']['decision']; message: string; count: number }[]
  runError: string | null
}) {
  const look = busy || !decision ? VERDICT_LOOK.pending : VERDICT_LOOK[decision]
  const { Icon } = look
  return (
    <div className={cn('flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-start', look.className)}>
      <Icon className={cn('size-6 shrink-0', busy && 'animate-spin')} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-base font-semibold">{look.title}</span>
        <span className="text-sm opacity-90">{look.next}</span>
        {!busy && reasons.length > 0 && (
          <ul className="mt-1 flex flex-col gap-0.5 text-sm">
            {reasons.map((r) => (
              <li key={`${r.decision}|${r.message}`} className="flex gap-2">
                <span aria-hidden>•</span>
                <span>
                  {r.message}
                  {r.count > 1 && <span className="opacity-70"> (×{r.count})</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
        {runError && <span className="text-sm text-destructive">La última corrida falló: {runError}</span>}
      </div>
      {!busy && decision === 'human_review' && canExecute() && (
        <Button asChild size="sm" className="shrink-0">
          <Link to="/review">Revisar campos</Link>
        </Button>
      )}
    </div>
  )
}

const VERDICT_LOOK = {
  continue: {
    Icon: CheckCircle2,
    title: 'Puede continuar',
    next: 'Los documentos están completos y las validaciones pasaron.',
    className: 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200',
  },
  human_review: {
    Icon: CircleAlert,
    title: 'Necesita revisión humana',
    next: 'Revisa los campos y observaciones de abajo; el veredicto se actualiza al corregir.',
    className: 'border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200',
  },
  return_to_client: {
    Icon: CircleX,
    title: 'Devolver al cliente',
    next: 'Pide al cliente lo que falta; al llegar, el expediente se vuelve a evaluar solo.',
    className: 'border-red-300 bg-red-50 text-red-900 dark:bg-red-950/30 dark:text-red-200',
  },
  pending: {
    Icon: Loader2,
    title: 'En proceso',
    next: 'Se están leyendo y validando los documentos.',
    className: 'border-sky-300 bg-sky-50 text-sky-900 dark:bg-sky-950/30 dark:text-sky-200',
  },
} as const

/** The case's name, its decision and one way to act; everything else in "⋯", the technical folded (VRT-75). */
function CaseHeader({ result, statusLabel, busy, onDeleted }: { result: CaseResult; statusLabel?: string; busy: boolean; onDeleted: () => void }) {
  const reprocess = useReprocessCase()
  const { data: profiles } = useProcessProfiles()
  const processName = result.case.profile ? (profiles?.find((p) => p.key === result.case.profile?.key)?.name ?? result.case.profile.key) : 'Sin proceso'
  const remove = useDeleteAction({ path: `/v1/cases/${result.case.id}`, question: DELETE_CASE, askReason: true, onDone: onDeleted })
  const caseId = result.case.id
  const arrived = new Date(result.case.created_at).toLocaleString('es', { dateStyle: 'medium', timeStyle: 'short' })
  return (
    <div className="flex flex-col gap-2">
      <Link to="/cases" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ChevronLeft className="size-4" /> Expedientes
      </Link>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">{result.case.external_ref ?? result.case.id.slice(0, 8)}</h1>
          <span className="text-sm text-muted-foreground">
            {processName} · llegó el {arrived}
            {statusLabel && ` · ${statusLabel}`}
          </span>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to={`/asistente?case=${caseId}`}>
            <Bot className="size-4" /> Preguntar al asistente
          </Link>
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="icon" className="size-8" aria-label="Más acciones">
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            {canExecute() && (
              <DropdownMenuItem
                disabled={busy || reprocess.isPending}
                onSelect={() => {
                  if (!confirm('Se vuelve a leer todo el expediente con el modelo; las correcciones se conservan. ¿Continuar?')) return
                  reprocess.mutate(
                    { caseId, scope: { kind: 'case' } },
                    { onSuccess: (run) => toast.success(`Corrida ${run.run_number} en curso.`), onError: (e) => toast.error(errorDetail(e)) },
                  )
                }}
              >
                <RefreshCw className="size-4" /> Volver a procesar
              </DropdownMenuItem>
            )}
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Descargar resultado</DropdownMenuLabel>
            {EXPORTS.map((e) => (
              <DropdownMenuItem key={e.format} onSelect={() => downloadCaseResult(caseId, e.format).catch((err) => toast.error(errorDetail(err)))}>
                <Download className="size-4" /> {e.label}
              </DropdownMenuItem>
            ))}
            {result.run && (
              <DropdownMenuItem asChild>
                <Link to={`/prompts?case=${caseId}`}>
                  <MessageSquareText className="size-4" /> Instrucciones usadas
                </Link>
              </DropdownMenuItem>
            )}
            {isAdmin() && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" disabled={remove.pending} onSelect={remove.run}>
                  <Trash2 className="size-4" /> Eliminar expediente
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <details className="text-xs text-muted-foreground">
        <summary className="w-fit cursor-pointer select-none hover:text-foreground">Detalle técnico</summary>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          <span>
            {result.case.profile
              ? `Proceso ${result.case.profile.key} v${result.case.profile.version} · catálogo de datos v${result.case.profile.semantic_catalog_version}`
              : 'Sin proceso'}
          </span>
          <span>Canal {result.case.channel}</span>
          {result.run && <span>Corrida {result.run.run_number} ({RUN_STATUS[result.run.status] ?? result.run.status}){runLabel(result.run)}</span>}
          <span className="font-mono">{caseId}</span>
        </div>
      </details>
    </div>
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
  const navigate = useNavigate()
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
      <CaseHeader result={result} statusLabel={summary?.progress.status_label} busy={busy} onDeleted={() => navigate('/cases')} />
      {summary?.personal_data && (
        <PersonalDataBar
          caseId={result.case.id}
          visible={summary.personal_data.visible}
          canReveal={summary.personal_data.can_reveal}
          removed={{ at: summary.personal_data.removed_at, reason: summary.personal_data.removed_reason, retentionDays: summary.personal_data.retention_days }}
        />
      )}

      <VerdictBanner decision={decision} busy={busy} reasons={reasons} runError={result.run?.error ?? null} />

      {summary && (busy || summary.progress.failed_documents > 0) && (
        <Card>
          <CardContent className="py-4">
            <ProgressFunnel progress={summary.progress} />
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,560px)]">
        <div className="flex min-w-0 flex-col gap-4">
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
                    <StatusBadge status={d.needs_review ? 'needs_review' : d.status} />
                  </button>
                  <span className="ml-auto flex items-center gap-2">
                    {!d.parent_document_id && !segmented.has(d.id) && (
                      <ReprocessButton caseId={result.case.id} scope={{ kind: 'document', document_id: d.id }} label="Re-extraer" busy={busy} />
                    )}
                    <Link to={`/documents/${d.id}`} className="text-xs underline">
                      campos
                    </Link>
                    {isAdmin() && !summary?.personal_data?.removed_at && (
                      <DeleteButton
                        iconOnly
                        path={`/documents/${d.id}`}
                        label="Eliminar documento"
                        question="Se eliminará para siempre este documento con su archivo y lo leído de él, y el expediente se volverá a evaluar sin él."
                      />
                    )}
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
