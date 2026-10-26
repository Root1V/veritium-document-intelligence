// What did not pass (VRT-104): how many errors, warnings and notes there
// are — each a filter in its traffic-light colour — and the findings grouped
// by case. A finding between documents is said once, with every document it
// was seen in, instead of once per document; the data that do not match are
// one table per case — each datum, and what each document says — instead of
// the consistency rule's run-on sentences. Each finding says what to do with
// it (VRT-105): review it here — correct the datum or confirm it — or ask the
// AI to look into it; its state shows once done. The rule stays folded.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, AlertTriangle, CircleCheck, FileText, FolderOpen, Info, Loader2, Sparkles, type LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import { ReviewDialog } from '@/components/validation/ReviewDialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute } from '@/lib/auth'
import { formatValue, humanizeFieldName } from '@/lib/extraction'
import { useTypeName } from '@/lib/labels'
import { useCaseResult, useDocumentTypeCatalog, useInvestigate, useSemanticCatalog, useValidationLog } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ValidationIssueEntry } from '@/types/api'

const ALL = '__all__'
// The rule that compares each datum across the case's documents (VRT-23).
const CONSISTENCY = 'semantic.attribute_consistency'
const STEP = 200
const IN_FLIGHT = 6

const CATEGORY: Record<string, string> = {
  cross_document: 'Entre documentos',
  self: 'Interna del documento',
  reference_data: 'Datos de referencia',
  request_input: 'Datos de entrada',
  conditional: 'Condicional',
  external_system: 'Sistema externo',
}

type Severity = ValidationIssueEntry['severity']
const SEVERITY: Record<Severity, { label: string; plural: string; icon: LucideIcon; text: string; tile: string }> = {
  error: { label: 'error', plural: 'Errores', icon: AlertCircle, text: 'text-red-600 dark:text-red-400', tile: 'ring-red-500' },
  warning: { label: 'advertencia', plural: 'Advertencias', icon: AlertTriangle, text: 'text-amber-600 dark:text-amber-400', tile: 'ring-amber-500' },
  info: { label: 'nota', plural: 'Informativas', icon: Info, text: 'text-muted-foreground', tile: 'ring-border' },
}
const SEVERITIES = Object.keys(SEVERITY) as Severity[]
const HINT: Record<Severity, string> = {
  error: 'Algo que no cuadra y frena la decisión.',
  warning: 'Conviene revisarlo; no frena por sí solo.',
  info: 'Para tener en cuenta.',
}

/** One finding of a case, with every document it was seen in. */
interface Finding {
  issue: ValidationIssueEntry
  issues: ValidationIssueEntry[] // one per document it was seen in
  documents: { id: string; name: string }[]
}

function groupByCase(issues: ValidationIssueEntry[]) {
  const cases = new Map<string, { id: string; ref: string | null | undefined; at: string; findings: Map<string, Finding> }>()
  for (const issue of issues) {
    const group = cases.get(issue.batch_id) ?? { id: issue.batch_id, ref: issue.case_ref, at: issue.created_at, findings: new Map<string, Finding>() }
    const key = `${issue.rule_id}|${issue.message}`
    const finding = group.findings.get(key) ?? { issue, issues: [], documents: [] }
    finding.issues.push(issue)
    if (issue.document_id && !finding.documents.some((d) => d.id === issue.document_id))
      finding.documents.push({ id: issue.document_id, name: issue.document_filename ?? 'documento' })
    group.findings.set(key, finding)
    cases.set(issue.batch_id, group)
  }
  return [...cases.values()].map((c) => ({ ...c, findings: [...c.findings.values()].sort((a, b) => SEVERITIES.indexOf(a.issue.severity) - SEVERITIES.indexOf(b.issue.severity)) }))
}

/** What the AI said, or that it is on it (VRT-66). */
function AiAnswer({ issues }: { issues: ValidationIssueEntry[] }) {
  // Of the times it was asked: the one under way, else the one that answered.
  const rank = { running: 0, done: 1, failed: 2 } as const
  const investigation = issues
    .map((i) => i.investigation)
    .filter((i) => !!i)
    .sort((a, b) => rank[a.status] - rank[b.status])[0]
  if (!investigation) return null
  if (investigation.status === 'running')
    return (
      <p className="inline-flex items-center gap-1.5 text-xs text-sky-700 dark:text-sky-300">
        <Loader2 className="size-3 animate-spin" /> La IA lo está investigando…
      </p>
    )
  if (investigation.status === 'failed') return <p className="text-xs text-muted-foreground">La IA no pudo investigarlo esta vez.</p>
  return (
    <p className="rounded-md border border-sky-500/30 bg-sky-500/5 px-2 py-1 text-xs">
      <span className="font-medium text-sky-700 dark:text-sky-300">La IA: </span>
      {investigation.diagnosis}
      {investigation.action_label && <span className="font-medium"> → {investigation.action_label}</span>}
    </p>
  )
}

/** Review it here, or ask the AI; once reviewed, how it ended. */
function Actions({ issues, caseId, onReview }: { issues: ValidationIssueEntry[]; caseId: string; onReview: (issue: ValidationIssueEntry) => void }) {
  const investigate = useInvestigate(caseId)
  const pending = issues.filter((i) => i.review_status === 'pending')
  const reviewed = issues.filter((i) => i.review_status === 'resolved' || i.review_status === 'dismissed')
  const asked = issues.some((i) => i.investigation && i.investigation.status !== 'failed')
  const may = canExecute()
  if (!pending.length && !reviewed.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {pending.length ? (
        <>
          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">Por revisar</span>
          {may && (
            <Button size="sm" className="h-7" onClick={() => onReview(pending[0])}>
              Revisar
            </Button>
          )}
          {may && !asked && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-sky-700 dark:text-sky-300"
              disabled={investigate.isPending}
              onClick={() =>
                investigate.mutate(pending[0].id, {
                  onSuccess: () => toast.success('La IA lo está investigando: su diagnóstico aparece aquí en un momento.'),
                  onError: (e) => toast.error(errorDetail(e)),
                })
              }
            >
              <Sparkles className="size-3.5" /> Pedir a la IA
            </Button>
          )}
        </>
      ) : (
        <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-1.5 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
          <CircleCheck className="size-3" /> {reviewed.some((i) => i.review_status === 'resolved') ? 'Corregida' : 'Confirmada sin cambios'}
        </span>
      )}
    </div>
  )
}

function FindingRow({ finding, onReview }: { finding: Finding; onReview: (issue: ValidationIssueEntry) => void }) {
  const { issue } = finding
  const meta = SEVERITY[issue.severity]
  const Icon = meta.icon
  const field = issue.field_label ?? (issue.field_path ? humanizeFieldName(issue.field_path) : null)
  const [technical, setTechnical] = useState(false)
  return (
    <div className="flex items-start gap-2.5 px-4 py-2">
      <Icon className={cn('mt-0.5 size-4 shrink-0', meta.text)} aria-label={meta.label} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-sm whitespace-pre-line">{issue.message}</p>
        <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
          <span className="rounded bg-muted px-1.5 py-0.5 text-foreground">{CATEGORY[issue.category] ?? issue.category}</span>
          {field && <span className="rounded bg-muted px-1.5 py-0.5 text-foreground">{field}</span>}
          {finding.documents.map((d) => (
            <Link key={d.id} to={`/documents/${d.id}`} className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-primary hover:bg-primary/10">
              <FileText className="size-3" /> {d.name}
            </Link>
          ))}
          <button type="button" onClick={() => setTechnical(!technical)} className="px-1 hover:text-foreground">
            {technical ? 'Ocultar detalle' : 'Detalle técnico'}
          </button>
        </div>
        {technical && (
          <p className="text-xs text-muted-foreground">
            <code>{issue.rule_id}</code> · {issue.explanation}
          </p>
        )}
        <AiAnswer issues={finding.issues} />
        <Actions issues={finding.issues} caseId={issue.batch_id} onReview={onReview} />
      </div>
    </div>
  )
}

/** The data of a case that its documents state differently: each datum,
 * and every value with the documents that say it. */
function DataThatDoNotMatch({ caseId, findings, turn, onDone, onReview }: { caseId: string; findings: Finding[]; turn: boolean; onDone: () => void; onReview: (issue: ValidationIssueEntry) => void }) {
  // Asked for a few at a time: every case asking at once kept the API busy (VRT-104).
  const { data: result, isLoading, isFetched } = useCaseResult(turn ? caseId : undefined)
  useEffect(() => {
    if (isFetched) onDone()
  }, [isFetched]) // eslint-disable-line react-hooks/exhaustive-deps
  const { data: semantic } = useSemanticCatalog()
  const typeName = useTypeName()
  const investigate = useInvestigate(caseId)
  const issues = findings.flatMap((f) => f.issues)
  // The finding naming the most data is the one to look into.
  const widest = [...issues].sort((a, b) => b.message.length - a.message.length)[0]
  const asked = issues.some((i) => i.investigation && i.investigation.status !== 'failed')
  const conflicts = Object.values(result?.entities ?? {})
    .flatMap((entities) => Object.values(entities).flatMap((attrs) => Object.values(attrs)))
    .filter((a) => a.status === 'conflict')
  if (!turn || isLoading) return <Loader2 className="mx-4 my-3 size-4 animate-spin text-muted-foreground" />
  // A case read again since: its findings say it as they were.
  if (!conflicts.length) return <>{findings.map((f) => <FindingRow key={`${f.issue.rule_id}|${f.issue.message}`} finding={f} onReview={onReview} />)}</>
  const label = (role: string, attribute: string) => {
    const name = semantic?.catalog.attributes.find((a) => a.key === attribute)?.name ?? humanizeFieldName(attribute.split('.').pop() ?? attribute)
    const who = semantic?.catalog.roles.find((r) => r.key === role)?.name ?? role
    return `${name} del ${who.toLowerCase()}`
  }
  return (
    <div className="flex items-start gap-2.5 px-4 py-2">
      <AlertCircle className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" aria-label="error" />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <p className="text-sm">No coinciden entre documentos:</p>
        <dl className="flex flex-col gap-1.5 text-sm">
          {conflicts.map((a) => {
            const byValue = new Map<string, string[]>()
            for (const s of a.sources) {
              const v = formatValue(s.value)
              byValue.set(v, [...(byValue.get(v) ?? []), typeName(s.document_type)])
            }
            return (
              <div key={`${a.role}.${a.attribute}`} className="flex flex-col gap-0.5">
                <dt className="text-xs text-muted-foreground">{label(a.role, a.attribute)}</dt>
                <dd className="flex flex-wrap gap-1">
                  {[...byValue.entries()].map(([value, docs]) => (
                    <span key={value} className="inline-flex items-baseline gap-1.5 rounded border bg-background px-1.5 leading-6">
                      <span className="font-semibold">{value}</span>
                      <span className="text-xs text-muted-foreground">{docs.join(', ')}</span>
                    </span>
                  ))}
                </dd>
              </div>
            )
          })}
        </dl>
        <AiAnswer issues={issues} />
        <div className="flex flex-wrap items-center gap-1.5">
          {canExecute() && !asked && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-sky-700 dark:text-sky-300"
              disabled={investigate.isPending}
              onClick={() =>
                investigate.mutate(widest.id, {
                  onSuccess: () => toast.success('La IA está buscando qué documento tiene el valor correcto.'),
                  onError: (e) => toast.error(errorDetail(e)),
                })
              }
            >
              <Sparkles className="size-3.5" /> Pedir a la IA cuál es el correcto
            </Button>
          )}
          <Button size="sm" variant="ghost" className="h-7" asChild>
            <Link to={`/cases/${caseId}`}>Ver los documentos</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}

function SeverityTile({ severity, active, onClick, filters }: { severity: Severity; active: boolean; onClick: () => void; filters: { category?: string; document_type?: string } }) {
  const { data } = useValidationLog({ ...filters, severity, limit: 1 })
  const meta = SEVERITY[severity]
  const Icon = meta.icon
  return (
    <button type="button" onClick={onClick} className={cn('flex flex-col gap-1 rounded-xl border bg-card p-4 text-left transition hover:border-primary/40', active && `ring-2 ${meta.tile}`)}>
      <span className="flex items-center justify-between gap-2">
        <span className={cn('inline-flex items-center gap-1.5 font-semibold', meta.text)}>
          <Icon className="size-4" /> {meta.plural}
        </span>
        <span className="text-2xl font-semibold tabular-nums">{data?.total ?? '—'}</span>
      </span>
      <span className="text-xs text-muted-foreground">{HINT[severity]}</span>
    </button>
  )
}

export function ValidationPage() {
  const [category, setCategory] = useState<string | null>(null)
  const [severity, setSeverity] = useState<Severity | null>(null)
  const [documentType, setDocumentType] = useState(ALL)
  const [limit, setLimit] = useState(STEP)
  const [pendingOnly, setPendingOnly] = useState(false)
  const [reviewing, setReviewing] = useState<ValidationIssueEntry | null>(null)
  const { data: catalog } = useDocumentTypeCatalog()
  const scope = { category: category ?? undefined, document_type: documentType === ALL ? undefined : documentType }
  const { data, isLoading, isFetching, isError } = useValidationLog({ ...scope, severity: severity ?? undefined, limit })
  const groups = groupByCase((data?.issues ?? []).filter((i) => !pendingOnly || i.review_status === 'pending'))
  const [done, setDone] = useState(0)
  const withConflicts = groups.filter((g) => g.findings.some((f) => f.issue.rule_id === CONSISTENCY)).map((g) => g.id)
  const filtered = category || severity || documentType !== ALL || pendingOnly
  const pendingCount = (data?.issues ?? []).filter((i) => i.review_status === 'pending').length

  const reset = <T,>(set: (v: T) => void) => (v: T) => (set(v), setLimit(STEP))

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Observaciones de validación</h1>
        <p className="text-muted-foreground">Lo que no se cumplió en cada expediente, agrupado por expediente. Una comprobación que pasa no aparece aquí.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {SEVERITIES.map((s) => (
          <SeverityTile key={s} severity={s} active={severity === s} filters={scope} onClick={() => reset(setSeverity)(severity === s ? null : s)} />
        ))}
      </div>

      <ol className="grid gap-2 rounded-xl border bg-muted/40 p-3 text-sm sm:grid-cols-3">
        {[
          ['Revisa', 'Abre la observación y mira el dato en el documento.'],
          ['Corrige o confirma', 'Corrige si se leyó mal; si el documento de verdad dice eso, confírmalo con el motivo.'],
          ['¿Dudas?', 'Pide a la IA que lo investigue: deja un diagnóstico con su evidencia, y tú decides.'],
        ].map(([title, text], i) => (
          <li key={title} className="flex items-start gap-2">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">{i + 1}</span>
            <span>
              <span className="font-medium">{title}.</span> <span className="text-muted-foreground">{text}</span>
            </span>
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setPendingOnly(!pendingOnly)}
          className={cn('rounded-full border px-3 py-1 text-xs font-medium transition', pendingOnly ? 'border-amber-500 bg-amber-500 text-white' : 'border-amber-500/50 bg-card text-amber-700 hover:border-amber-500 dark:text-amber-300')}
        >
          Por revisar {pendingCount > 0 && <span className="opacity-80">{pendingCount}</span>}
        </button>
        {Object.entries(CATEGORY).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => reset(setCategory)(category === key ? null : key)}
            className={cn('rounded-full border px-3 py-1 text-xs font-medium transition', category === key ? 'border-primary bg-primary text-primary-foreground' : 'bg-card hover:border-primary/40')}
          >
            {label}
          </button>
        ))}
        <Select value={documentType} onValueChange={reset(setDocumentType)}>
          <SelectTrigger className="h-8 w-52">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos los documentos</SelectItem>
            <SelectItem value="generic">Otro documento</SelectItem>
            {catalog?.registered.map((t) => (
              <SelectItem key={t.name} value={t.name}>
                {t.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {filtered && (
          <Button size="sm" variant="ghost" onClick={() => (setCategory(null), setSeverity(null), setDocumentType(ALL), setPendingOnly(false), setLimit(STEP))}>
            Ver todas
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar las observaciones: el servidor de Veritium no responde.</p>
      ) : !groups.length ? (
        <p className="text-sm text-muted-foreground">{filtered ? 'Ninguna observación con estos filtros.' : 'Todo se cumplió: no hay observaciones.'}</p>
      ) : (
        <div className={cn('gap-3 xl:columns-2 2xl:columns-3', isFetching && 'opacity-60')}>
          {groups.map((g) => {
            // The consistency findings show as one table: they count once.
            const shownFindings = [...g.findings.filter((f) => f.issue.rule_id !== CONSISTENCY), ...g.findings.filter((f) => f.issue.rule_id === CONSISTENCY).slice(0, 1)]
            const counts = SEVERITIES.map((s) => [s, shownFindings.filter((f) => f.issue.severity === s).length] as const).filter(([, n]) => n)
            return (
              <section key={g.id} className="mb-3 break-inside-avoid overflow-hidden rounded-xl border bg-card">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-muted/40 px-4 py-1.5">
                  <FolderOpen className="size-4 text-muted-foreground" />
                  <Link to={`/cases/${g.id}`} className="font-semibold hover:underline">
                    {g.ref ?? `Expediente ${g.id.slice(0, 8)}`}
                  </Link>
                  <span className="text-xs text-muted-foreground">{new Date(g.at).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })}</span>
                  <span className="ml-auto flex flex-wrap gap-3 text-xs">
                    {counts.map(([s, n]) => (
                      <span key={s} className={cn('inline-flex items-center gap-1 font-medium', SEVERITY[s].text)}>
                        {n} {n === 1 ? SEVERITY[s].label : SEVERITY[s].plural.toLowerCase()}
                      </span>
                    ))}
                  </span>
                </div>
                <div className="flex flex-col divide-y">
                  {g.findings.some((f) => f.issue.rule_id === CONSISTENCY) && (
                    <DataThatDoNotMatch
                      caseId={g.id}
                      findings={g.findings.filter((f) => f.issue.rule_id === CONSISTENCY)}
                      turn={withConflicts.indexOf(g.id) < done + IN_FLIGHT}
                      onDone={() => setDone((n) => n + 1)}
                      onReview={setReviewing}
                    />
                  )}
                  {g.findings
                    .filter((f) => f.issue.rule_id !== CONSISTENCY)
                    .map((f) => (
                      <FindingRow key={`${f.issue.rule_id}|${f.issue.message}`} finding={f} onReview={setReviewing} />
                    ))}
                </div>
              </section>
            )
          })}
          {data && data.total > data.issues.length && (
            <Button variant="outline" className="mx-auto flex" disabled={isFetching} onClick={() => setLimit(limit + STEP)}>
              {isFetching && <Loader2 className="size-4 animate-spin" />} Ver anteriores ({data.total - data.issues.length} más)
            </Button>
          )}
        </div>
      )}
      {reviewing?.review_item_id && <ReviewDialog reviewItemId={reviewing.review_item_id} finding={reviewing.message} onClose={() => setReviewing(null)} />}
    </div>
  )
}
