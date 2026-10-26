// The end-to-end view of a case (VRT-38): what to do next and why
// (verdict, conditions), what the case says (consolidated entities), and
// where each piece of it came from — every source, document and finding
// opens the evidence viewer on its page with its box. Each of them can be
// reprocessed on its own as a new run (VRT-40), and the result exported (VRT-41).
// VRT-110: the decision says what to do in one line, with how many things
// are behind it; the data are told by their business names, grouped by
// person, the ones the documents state differently first, each value with
// the documents that say it; findings without codes; the rest folded.
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, Bot, CheckCircle2, ChevronLeft, CircleAlert, CircleX, Download, FileText, Info, Loader2, MessageSquareText, MoreHorizontal, RefreshCw, Search, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { useAssistant } from '@/lib/assistant'
import { InvestigationPanel } from '@/components/cases/InvestigationPanel'
import { LensesCard } from '@/components/cases/LensesCard'
import { ProgressFunnel } from '@/components/cases/ProgressFunnel'
import { EvidenceViewer } from '@/components/documents/EvidenceViewer'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute, isAISpecialist, isAdmin } from '@/lib/auth'
import { useDeleteAction } from '@/components/DeleteButton'
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
  useSemanticCatalog,
  useWaiveCondition,
  type CaseExportFormat,
} from '@/lib/queries'
import type { CaseCondition, CaseFinding, CaseResult, ReprocessScope, ResolvedAttribute } from '@/types/api'
import { PersonalDataBar } from '@/components/cases/PersonalDataBar'

interface Evidence {
  documentId: string
  page: number
  bbox: [number, number, number, number] | null
  label: string
}

// The rule that compares each datum across the case's documents (VRT-23): shown as the data that do not match.
const CONSISTENCY = 'semantic.attribute_consistency'

function show(value: unknown): string {
  if (value === null || value === undefined) return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function ConditionRow({ caseId, condition, what }: { caseId: string; condition: CaseCondition; what: string }) {
  const waive = useWaiveCondition()
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(false)
  const missing = condition.status === 'open'
  return (
    <div className="flex flex-col gap-2 px-4 py-2.5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {missing ? <CircleX className="size-4 shrink-0 text-red-600" /> : <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />}
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="font-medium">{condition.label}</span>
          <span className="text-xs text-muted-foreground">
            {missing ? 'Falta' : condition.status === 'waived' ? `Dispensado por ${condition.waived_by}: ${condition.waived_reason}` : 'Cumplido'} · {what}
          </span>
        </span>
        {missing && canExecute() && !open && (
          <Button size="sm" variant="ghost" className="h-7" onClick={() => setOpen(true)}>
            Dispensar
          </Button>
        )}
      </div>
      {open && (
        <div className="flex gap-2 pl-6">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Por qué se dispensa (queda en la auditoría)" className="h-8 text-xs" />
          <Button
            size="sm"
            disabled={reason.trim().length < 3 || waive.isPending}
            onClick={() =>
              waive.mutate(
                { caseId, conditionId: condition.id, reason },
                { onSuccess: () => toast.success('Requisito dispensado; la decisión se recalculó.'), onError: (e) => toast.error(errorDetail(e)) },
              )
            }
          >
            Confirmar
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
            Cancelar
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
function ReprocessButton({ caseId, scope, label, busy, iconOnly = false }: { caseId: string; scope: ReprocessScope; label: string; busy: boolean; iconOnly?: boolean }) {
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
      title={busy ? 'Hay una corrida en curso' : label}
      aria-label={label}
      onClick={() => (reextracts ? setAsking(true) : start())}
    >
      <RefreshCw className="size-3" />
      {!iconOnly && label}
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
  summary,
  runError,
}: {
  decision: CaseResult['verdict']['decision'] | null
  busy: boolean
  reasons: { decision: CaseResult['verdict']['decision']; message: string; count: number }[]
  summary: string[]
  runError: string | null
}) {
  const look = busy || !decision ? VERDICT_LOOK.pending : VERDICT_LOOK[decision]
  const { Icon } = look
  return (
    <div className={cn('flex flex-col gap-3 rounded-xl border p-4 sm:flex-row sm:items-start', look.className)}>
      <Icon className={cn('size-6 shrink-0', busy && 'animate-spin')} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-base font-semibold">{look.title}</span>
        <span className="text-sm opacity-90">{look.next}</span>
        {!busy && summary.length > 0 && <span className="text-sm font-medium">{summary.join(' · ')}</span>}
        {!busy && reasons.length > 0 && (
          <details className="text-sm">
            <summary className="w-fit cursor-pointer opacity-80 select-none hover:opacity-100">Ver los motivos ({reasons.length})</summary>
            <ul className="mt-1 flex flex-col gap-0.5">
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
          </details>
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
    next: 'Revisa lo de abajo: al corregir, la decisión se vuelve a calcular sola.',
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
  const assistant = useAssistant()
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
        <Button variant="outline" size="sm" onClick={() => assistant.openFor(caseId)}>
          <Bot className="size-4" /> Preguntar al asistente
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

/** What the case says, by person (VRT-110): the data its documents state
 * differently first — each value with the documents that say it — then the
 * rest, one line each. Every source opens the document where it is. */
function CaseData({
  result,
  typeName,
  busy,
  onEvidence,
}: {
  result: CaseResult
  typeName: Record<string, string>
  busy: boolean
  onEvidence: (e: Evidence) => void
}) {
  const { data: semantic } = useSemanticCatalog()
  const attrName = (key: string) => semantic?.catalog.attributes.find((a) => a.key === key)?.name ?? key.split('.').pop()!.replace(/_/g, ' ')
  const roleName = (key: string) => semantic?.catalog.roles.find((r) => r.key === key)?.name ?? key
  const roles = Object.entries(result.entities).map(([role, entities]) => {
    const attrs = Object.values(entities).flatMap((a) => Object.values(a))
    return { role, attrs: [...attrs.filter((a) => a.status === 'conflict'), ...attrs.filter((a) => a.status !== 'conflict')] }
  })
  roles.sort((a, b) => Number(b.attrs.some((x) => x.status === 'conflict')) - Number(a.attrs.some((x) => x.status === 'conflict')))
  const docOf = (s: ResolvedAttribute['sources'][number]) => typeName[s.document_type] ?? s.document_type
  const open = (s: ResolvedAttribute['sources'][number]) =>
    onEvidence({ documentId: s.document_id, page: s.page ?? 0, bbox: s.bbox, label: `${docOf(s)}${s.page !== null ? ` · pág. ${s.page + 1}` : ''}` })

  if (!roles.length) return null
  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-semibold">Datos del expediente</h2>
      {roles.map(({ role, attrs }) => (
        <div key={role} className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b bg-muted/40 px-4 py-2 text-sm font-semibold">{roleName(role)}</div>
          <div className="flex flex-col divide-y">
            {attrs.map((a) => {
              const conflict = a.status === 'conflict'
              const byValue = new Map<string, ResolvedAttribute['sources']>()
              for (const src of a.sources) byValue.set(show(src.value), [...(byValue.get(show(src.value)) ?? []), src])
              return (
                <div key={a.attribute} className={cn('group flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-2 text-sm', conflict && 'bg-red-500/5')}>
                  <span className="w-48 shrink-0 text-muted-foreground">{attrName(a.attribute)}</span>
                  {conflict ? (
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700 dark:text-red-400">
                        <AlertTriangle className="size-3" /> No coincide entre documentos
                      </span>
                      <span className="flex flex-wrap gap-1">
                        {[...byValue.entries()].map(([value, sources]) => (
                          <button
                            key={value}
                            type="button"
                            onClick={() => open(sources[0])}
                            className="inline-flex items-baseline gap-1.5 rounded border bg-background px-1.5 leading-6 hover:border-primary/40"
                          >
                            <span className="font-semibold">{value}</span>
                            <span className="text-xs text-muted-foreground">{sources.map(docOf).join(', ')}</span>
                          </button>
                        ))}
                      </span>
                    </span>
                  ) : (
                    <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2">
                      <span className="font-medium">{show(a.value)}</span>
                      <span className="flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
                        {a.status === 'consistent' && <span className="text-emerald-700 dark:text-emerald-400">✓ coincide en</span>}
                        {a.sources.map((src, i) => (
                          <button key={i} type="button" onClick={() => open(src)} className="hover:text-foreground hover:underline">
                            {docOf(src)}
                            {i < a.sources.length - 1 && ','}
                          </button>
                        ))}
                      </span>
                    </span>
                  )}
                  <span className="opacity-0 transition group-hover:opacity-100">
                    <ReprocessButton caseId={result.case.id} scope={{ kind: 'attribute', attribute: a.attribute }} label="Volver a evaluar este dato" busy={busy} iconOnly />
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </section>
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
  // A finding seen in several documents is said once, with all of them; the data that do not match are in «Datos del expediente».
  const findings = Object.values(
    result.findings
      .filter((f) => f.rule_id !== CONSISTENCY)
      .reduce<Record<string, { finding: CaseFinding; documents: string[] }>>((acc, f) => {
        const k = `${f.rule_id}|${f.message}`
        acc[k] ??= { finding: f, documents: [] }
        if (f.document_id && !acc[k].documents.includes(f.document_id)) acc[k].documents.push(f.document_id)
        return acc
      }, {}),
  )
  const conflicts = Object.values(result.entities).flatMap((e) => Object.values(e).flatMap((a) => Object.values(a))).filter((a) => a.status === 'conflict').length
  const missing = result.conditions.filter((c) => c.status === 'open').length
  const toReview = result.documents.filter((d) => d.needs_review).length
  const todo = [
    missing && (missing === 1 ? '1 requisito sin cumplir' : `${missing} requisitos sin cumplir`),
    conflicts && (conflicts === 1 ? '1 dato no coincide entre documentos' : `${conflicts} datos no coinciden entre documentos`),
    findings.length && (findings.length === 1 ? '1 observación' : `${findings.length} observaciones`),
    toReview && (toReview === 1 ? '1 documento con datos por revisar' : `${toReview} documentos con datos por revisar`),
  ].filter(Boolean) as string[]
  const conditionWhat = (c: CaseCondition) =>
    c.kind === 'missing_evidence' ? `Lo prueba cualquier documento con ${(c.attributes ?? []).join(', ').replace(/[a-z_]+\./g, '').replace(/_/g, ' ')}` : c.document_type ? (typeName[c.document_type] ?? c.document_type) : ''
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

      <VerdictBanner decision={decision} busy={busy} reasons={reasons} summary={todo} runError={result.run?.error ?? null} />

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
            <section className="flex flex-col gap-2">
              <h2 className="font-semibold">Lo que pide el proceso</h2>
              <div className="flex flex-col divide-y overflow-hidden rounded-xl border bg-card">
                {result.conditions.map((c) => (
                  <ConditionRow key={c.id} caseId={result.case.id} condition={c} what={conditionWhat(c)} />
                ))}
              </div>
            </section>
          )}

          <CaseData result={result} typeName={typeName} busy={busy} onEvidence={setEvidence} />

          {findings.length > 0 && (
            <section className="flex flex-col gap-2">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div className="flex flex-col">
                  <h2 className="font-semibold">Observaciones</h2>
                  <span className="text-xs text-muted-foreground">La IA puede investigar cada una y dejarte un diagnóstico con evidencia; no decide por ti.</span>
                </div>
                {canInvestigate && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={investigate.isPending || investigating}
                    onClick={() => investigate.mutate(undefined, { onError: (e) => toast.error(errorDetail(e)) })}
                  >
                    {investigating ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />} Investigar todas
                  </Button>
                )}
              </div>
              <div className="flex flex-col divide-y overflow-hidden rounded-xl border bg-card">
                {findings.map(({ finding: f, documents }) => {
                  const Icon = f.severity === 'error' ? CircleAlert : f.severity === 'warning' ? AlertTriangle : Info
                  return (
                    <div key={f.id} className="group flex flex-col gap-2 px-4 py-2.5 text-sm">
                      <div className="flex items-start gap-2.5">
                        <Icon
                          className={cn('mt-0.5 size-4 shrink-0', f.severity === 'error' ? 'text-red-600' : f.severity === 'warning' ? 'text-amber-600' : 'text-muted-foreground')}
                          aria-label={f.severity}
                        />
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5" title={f.rule_id}>
                          <span className="whitespace-pre-line">{f.message}</span>
                          <span className="flex flex-wrap gap-x-2 text-xs">
                            {documents.map((id) => (
                              <button key={id} type="button" className="inline-flex items-center gap-1 text-primary hover:underline" onClick={() => setEvidence(fieldEvidence(result, id, f.field_path))}>
                                <FileText className="size-3" /> {docName(id)}
                              </button>
                            ))}
                          </span>
                        </span>
                        <span className="flex shrink-0 items-center gap-1">
                          {canInvestigate && !investigationOf[f.id] && (
                            <Button size="sm" variant="ghost" className="h-7 text-sky-700 dark:text-sky-300" disabled={investigate.isPending} onClick={() => investigate.mutate(f.id, { onError: (e) => toast.error(errorDetail(e)) })}>
                              Investigar
                            </Button>
                          )}
                          <span className="opacity-0 transition group-hover:opacity-100">
                            <ReprocessButton caseId={result.case.id} scope={{ kind: 'rule', rule_id: f.rule_id }} label="Volver a evaluar esta regla" busy={busy} iconOnly />
                          </span>
                        </span>
                      </div>
                      {investigationOf[f.id] && (
                        <InvestigationPanel
                          investigation={investigationOf[f.id]}
                          onRetry={canInvestigate ? () => investigate.mutate(f.id, { onError: (e) => toast.error(errorDetail(e)) }) : undefined}
                          onEvidence={(documentId, page) => setEvidence({ documentId, page, bbox: null, label: `${docName(documentId)} · pág. ${page + 1}` })}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          <LensesCard caseId={result.case.id} onEvidence={(e) => setEvidence({ documentId: e.document_id, page: e.page, bbox: e.bbox, label: `${e.document_name} · pág. ${e.page + 1}` })} />

          <section className="flex flex-col gap-2">
            <h2 className="font-semibold">Documentos ({result.documents.length})</h2>
            <div className="flex flex-col divide-y overflow-hidden rounded-xl border bg-card">
              {result.documents.map((d) => {
                const active = selected?.documentId === d.id
                return (
                  <div key={d.id} className={cn('group flex items-center gap-3 px-4 py-2 text-sm', active && 'bg-primary/5')}>
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      onClick={() => setEvidence({ documentId: d.id, page: d.page_start ?? 0, bbox: null, label: d.filename })}
                    >
                      <FileText className="size-4 shrink-0 text-muted-foreground" />
                      <span className="flex min-w-0 flex-col">
                        <span className="font-medium">{d.document_type ? (typeName[d.document_type] ?? d.document_type) : 'Sin clasificar'}</span>
                        <span className="truncate text-xs text-muted-foreground">{d.filename}</span>
                      </span>
                    </button>
                    <StatusBadge status={d.needs_review ? 'needs_review' : d.status} />
                    <span className="flex items-center gap-1">
                      {!d.parent_document_id && !segmented.has(d.id) && (
                        <span className="opacity-0 transition group-hover:opacity-100">
                          <ReprocessButton caseId={result.case.id} scope={{ kind: 'document', document_id: d.id }} label="Volver a leer este documento" busy={busy} iconOnly />
                        </span>
                      )}
                      <Button size="sm" variant="ghost" className="h-7" asChild>
                        <Link to={`/documents/${d.id}`}>Ver datos</Link>
                      </Button>
                    </span>
                  </div>
                )
              })}
            </div>
          </section>
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
