// What did not pass (VRT-104, VRT-105): how many errors, warnings and notes
// there are — each a filter in its traffic-light colour — then a list of the
// cases with findings, one line each, and the chosen case beside it. There,
// each finding says what to do with it: review it here — correct the datum or
// confirm it — or ask the AI; the data its documents state differently are
// one table, not the consistency rule's run-on sentences. One case at a time:
// the list stays readable and only the open case is asked for its data.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, AlertTriangle, ChevronRight, CircleCheck, FileText, Info, Loader2, Sparkles, type LucideIcon } from 'lucide-react'
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

const CATEGORY: Record<string, string> = {
  cross_document: 'Entre documentos',
  self: 'Interna del documento',
  reference_data: 'Datos de referencia',
  request_input: 'Datos de entrada',
  conditional: 'Condicional',
  external_system: 'Sistema externo',
}

type Severity = ValidationIssueEntry['severity']
const SEVERITY: Record<Severity, { label: string; plural: string; icon: LucideIcon; text: string; dot: string; tile: string }> = {
  error: { label: 'error', plural: 'Errores', icon: AlertCircle, text: 'text-red-600 dark:text-red-400', dot: 'bg-red-500', tile: 'ring-red-500' },
  warning: { label: 'advertencia', plural: 'Advertencias', icon: AlertTriangle, text: 'text-amber-600 dark:text-amber-400', dot: 'bg-amber-500', tile: 'ring-amber-500' },
  info: { label: 'nota', plural: 'Informativas', icon: Info, text: 'text-muted-foreground', dot: 'bg-muted-foreground/40', tile: 'ring-border' },
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

interface CaseGroup {
  id: string
  ref: string | null | undefined
  at: string
  findings: Finding[] // data findings, worst first
  conflicts: Finding[] // the consistency rule's, shown as one table
}

function groupByCase(issues: ValidationIssueEntry[]): CaseGroup[] {
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
  const bySeverity = (a: Finding, b: Finding) => SEVERITIES.indexOf(a.issue.severity) - SEVERITIES.indexOf(b.issue.severity)
  return [...cases.values()].map((c) => {
    const all = [...c.findings.values()]
    return { ...c, findings: all.filter((f) => f.issue.rule_id !== CONSISTENCY).sort(bySeverity), conflicts: all.filter((f) => f.issue.rule_id === CONSISTENCY) }
  })
}

const pendingOf = (g: CaseGroup) => g.findings.filter((f) => f.issues.some((i) => i.review_status === 'pending')).length
const worstOf = (g: CaseGroup): Severity => (g.conflicts.length ? 'error' : (g.findings[0]?.issue.severity ?? 'info'))

/** What the AI said, or that it is on it (VRT-66): two lines, the rest on request. */
function AiAnswer({ issues }: { issues: ValidationIssueEntry[] }) {
  const [open, setOpen] = useState(false)
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
    <div className="flex flex-col gap-0.5 border-l-2 border-sky-500/60 pl-2 text-xs">
      <span className="font-medium text-sky-700 dark:text-sky-300">La IA sugiere: {investigation.action_label?.toLowerCase() ?? 'revisarlo'}</span>
      <p className={cn('text-muted-foreground', !open && 'line-clamp-2')}>{investigation.diagnosis}</p>
      <button type="button" onClick={() => setOpen(!open)} className="self-start text-sky-700 hover:underline dark:text-sky-300">
        {open ? 'Ver menos' : 'Ver más'}
      </button>
    </div>
  )
}

function AskAi({ caseId, issueId, label }: { caseId: string; issueId: string; label: string }) {
  const investigate = useInvestigate(caseId)
  return (
    <button
      type="button"
      disabled={investigate.isPending}
      className="inline-flex items-center gap-1 text-xs text-sky-700 hover:underline disabled:opacity-50 dark:text-sky-300"
      onClick={() =>
        investigate.mutate(issueId, {
          onSuccess: () => toast.success('La IA lo está investigando: su diagnóstico aparece aquí en un momento.'),
          onError: (e) => toast.error(errorDetail(e)),
        })
      }
    >
      <Sparkles className="size-3" /> {label}
    </button>
  )
}

function FindingCard({ finding, onReview }: { finding: Finding; onReview: (issue: ValidationIssueEntry) => void }) {
  const { issue } = finding
  const meta = SEVERITY[issue.severity]
  const Icon = meta.icon
  const pending = finding.issues.filter((i) => i.review_status === 'pending')
  const reviewed = finding.issues.filter((i) => i.review_status === 'resolved' || i.review_status === 'dismissed')
  const asked = finding.issues.some((i) => i.investigation && i.investigation.status !== 'failed')
  const may = canExecute()
  return (
    <div className="flex items-start gap-2.5 p-4">
      <Icon className={cn('mt-0.5 size-4 shrink-0', meta.text)} aria-label={meta.label} />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm whitespace-pre-line">{issue.message}</p>
          {pending.length ? (
            <span className="shrink-0 rounded bg-amber-500/10 px-1.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">Por revisar</span>
          ) : reviewed.length ? (
            <span className="inline-flex shrink-0 items-center gap-1 rounded bg-emerald-500/10 px-1.5 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
              <CircleCheck className="size-3" /> {reviewed.some((i) => i.review_status === 'resolved') ? 'Corregida' : 'Confirmada'}
            </span>
          ) : null}
        </div>
        <span className="flex flex-wrap gap-x-2 text-xs text-muted-foreground">
          {CATEGORY[issue.category] ?? issue.category}
          {finding.documents.map((d) => (
            <Link key={d.id} to={`/documents/${d.id}`} className="inline-flex items-center gap-1 text-primary hover:underline">
              <FileText className="size-3" /> {d.name}
            </Link>
          ))}
        </span>
        <AiAnswer issues={finding.issues} />
        {may && pending.length > 0 && (
          <div className="flex items-center gap-3">
            <Button size="sm" className="h-7" onClick={() => onReview(pending[0])}>
              Revisar
            </Button>
            {!asked && <AskAi caseId={issue.batch_id} issueId={pending[0].id} label="Pedir a la IA" />}
          </div>
        )}
      </div>
    </div>
  )
}

/** The data the case's documents state differently: each datum, and every value with the documents that say it. */
function DataThatDoNotMatch({ caseId, conflicts }: { caseId: string; conflicts: Finding[] }) {
  const { data: result, isLoading } = useCaseResult(caseId)
  const { data: semantic } = useSemanticCatalog()
  const typeName = useTypeName()
  const issues = conflicts.flatMap((f) => f.issues)
  // The finding naming the most data is the one to look into.
  const widest = [...issues].sort((a, b) => b.message.length - a.message.length)[0]
  const asked = issues.some((i) => i.investigation && i.investigation.status !== 'failed')
  const data = Object.values(result?.entities ?? {})
    .flatMap((entities) => Object.values(entities).flatMap((attrs) => Object.values(attrs)))
    .filter((a) => a.status === 'conflict')
  const label = (role: string, attribute: string) => {
    const name = semantic?.catalog.attributes.find((a) => a.key === attribute)?.name ?? humanizeFieldName(attribute.split('.').pop() ?? attribute)
    const who = semantic?.catalog.roles.find((r) => r.key === role)?.name ?? role
    return `${name} del ${who.toLowerCase()}`
  }
  return (
    <div className="flex items-start gap-2.5 p-4">
      <AlertCircle className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" aria-label="error" />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <p className="text-sm">{data.length === 1 ? 'Un dato no coincide' : `${data.length || 'Varios'} datos no coinciden`} entre los documentos</p>
        {isLoading ? (
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        ) : data.length ? (
          <dl className="flex flex-col gap-1.5 text-sm">
            {data.map((a) => {
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
        ) : (
          // Read again since: the findings say it as they were.
          conflicts.map((f) => (
            <p key={f.issue.id} className="text-xs whitespace-pre-line text-muted-foreground">
              {f.issue.message}
            </p>
          ))
        )}
        <AiAnswer issues={issues} />
        <div className="flex items-center gap-3">
          <Button size="sm" variant="outline" className="h-7" asChild>
            <Link to={`/cases/${caseId}`}>Ver los documentos</Link>
          </Button>
          {canExecute() && !asked && widest && <AskAi caseId={caseId} issueId={widest.id} label="Pedir a la IA cuál es el correcto" />}
        </div>
      </div>
    </div>
  )
}

function CaseRow({ group, active, onOpen }: { group: CaseGroup; active: boolean; onOpen: () => void }) {
  const pending = pendingOf(group)
  const titles = [...(group.conflicts.length ? ['Datos que no coinciden'] : []), ...group.findings.map((f) => f.issue.message.split('\n')[0])]
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn('flex w-full items-start gap-3 border-b px-4 py-3 text-left transition last:border-0 hover:bg-muted/50', active && 'bg-primary/5 shadow-[inset_3px_0_0] shadow-primary')}
    >
      <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full', SEVERITY[worstOf(group)].dot)} />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate font-semibold">{group.ref ?? `Expediente ${group.id.slice(0, 8)}`}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{new Date(group.at).toLocaleDateString('es-PE', { day: 'numeric', month: 'short' })}</span>
        </span>
        <span className="truncate text-xs text-muted-foreground">{titles.join(' · ')}</span>
        <span className="flex gap-1 text-xs">
          <span className="text-muted-foreground">{titles.length === 1 ? '1 observación' : `${titles.length} observaciones`}</span>
          {pending > 0 && <span className="font-medium text-amber-700 dark:text-amber-300">· {pending} por revisar</span>}
        </span>
      </span>
      <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" />
    </button>
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
  const [selected, setSelected] = useState<string | null>(null)
  const [reviewing, setReviewing] = useState<ValidationIssueEntry | null>(null)
  const { data: catalog } = useDocumentTypeCatalog()
  const scope = { category: category ?? undefined, document_type: documentType === ALL ? undefined : documentType }
  const { data, isLoading, isFetching, isError } = useValidationLog({ ...scope, severity: severity ?? undefined, limit })
  const all = groupByCase(data?.issues ?? [])
  const groups = pendingOnly ? all.filter((g) => pendingOf(g) > 0) : all
  const open = groups.find((g) => g.id === selected) ?? groups[0]
  const pendingCount = all.reduce((n, g) => n + pendingOf(g), 0)
  const filtered = category || severity || documentType !== ALL || pendingOnly

  const reset = <T,>(set: (v: T) => void) => (v: T) => (set(v), setLimit(STEP))

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Observaciones de validación</h1>
        <p className="text-muted-foreground">Lo que no se cumplió en cada expediente. Una comprobación que pasa no aparece aquí.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {SEVERITIES.map((s) => (
          <SeverityTile key={s} severity={s} active={severity === s} filters={scope} onClick={() => reset(setSeverity)(severity === s ? null : s)} />
        ))}
      </div>

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
      ) : !groups.length || !open ? (
        <p className="text-sm text-muted-foreground">{filtered ? 'Ninguna observación con estos filtros.' : 'Todo se cumplió: no hay observaciones.'}</p>
      ) : (
        <div className={cn('grid items-start gap-4 lg:grid-cols-[minmax(0,24rem)_1fr]', isFetching && 'opacity-60')}>
          <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
            {groups.map((g) => (
              <CaseRow key={g.id} group={g} active={g.id === open.id} onOpen={() => setSelected(g.id)} />
            ))}
            {data && data.total > data.issues.length && (
              <Button variant="ghost" className="m-2" disabled={isFetching} onClick={() => setLimit(limit + STEP)}>
                {isFetching && <Loader2 className="size-4 animate-spin" />} Ver anteriores
              </Button>
            )}
          </div>

          <section className="overflow-hidden rounded-xl border bg-card lg:sticky lg:top-16 lg:max-h-[calc(100svh-5rem)] lg:overflow-y-auto">
            <div className="flex flex-col gap-1 border-b bg-muted/40 px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <Link to={`/cases/${open.id}`} className="text-lg font-semibold hover:underline">
                  {open.ref ?? `Expediente ${open.id.slice(0, 8)}`}
                </Link>
                <span className="text-xs text-muted-foreground">{new Date(open.at).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })}</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Revisa cada observación: corrige el dato si se leyó mal, o confírmalo si el documento de verdad dice eso. ¿Dudas? Pide a la IA que lo investigue.
              </p>
            </div>
            <div className="flex flex-col divide-y">
              {open.conflicts.length > 0 && <DataThatDoNotMatch key={open.id} caseId={open.id} conflicts={open.conflicts} />}
              {open.findings.map((f) => (
                <FindingCard key={`${f.issue.rule_id}|${f.issue.message}`} finding={f} onReview={setReviewing} />
              ))}
            </div>
          </section>
        </div>
      )}
      {reviewing?.review_item_id && <ReviewDialog reviewItemId={reviewing.review_item_id} finding={reviewing.message} onClose={() => setReviewing(null)} />}
    </div>
  )
}
