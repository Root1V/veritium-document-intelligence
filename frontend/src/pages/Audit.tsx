// The audit (VRT-39, VRT-58, VRT-102): who changed a datum and why, and who
// saw a case's personal data — each record a sentence, grouped by day. A
// correction without a reason is said in amber; the platform's own automatic
// processes (tests, retention) are apart from what people did. The model and
// prompt behind a corrected value stay folded.
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Bot, FileText, Loader2, Search, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ACTION, CHANNEL, automatic, byDay, time } from '@/lib/audit'
import { isAdmin } from '@/lib/auth'
import { formatValue, humanizeFieldName } from '@/lib/extraction'
import { useTypeName } from '@/lib/labels'
import { useAuditLog, useCorrectionSummary, useDataAccessLog } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { AuditEntry, DataAccessEntry } from '@/types/api'

const NO_REASON = 'Sin motivo registrado'

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition', active ? 'border-primary bg-primary text-primary-foreground' : 'bg-card hover:border-primary/40')}
    >
      {children}
    </button>
  )
}

function Day({ day, children }: { day: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="sticky top-14 z-10 bg-background/95 py-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase backdrop-blur first-letter:uppercase">{day}</h3>
      <div className="flex flex-col divide-y rounded-xl border bg-card">{children}</div>
    </section>
  )
}

function CorrectionRow({ entry }: { entry: AuditEntry }) {
  const reason = entry.reason_label ?? NO_REASON
  return (
    <div className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:gap-4">
      <span className="w-16 shrink-0 text-xs text-muted-foreground tabular-nums">{time(entry.timestamp)}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className="font-medium">{entry.field_label ?? humanizeFieldName(entry.field_path)}</span>
          <span className="text-muted-foreground line-through decoration-red-400">{formatValue(entry.original_value.value)}</span>
          <ArrowRight className="size-3.5 text-muted-foreground" />
          <span className="font-semibold">{formatValue(entry.corrected_value.value)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <Link to={`/documents/${entry.document_id}`} className="inline-flex items-center gap-1 text-primary hover:underline">
            <FileText className="size-3" /> {entry.document_filename ?? 'Ver documento'}
          </Link>
          <span>· corrigió {entry.reviewer_identity}</span>
        </div>
        <div className="flex flex-wrap items-start gap-2 text-xs">
          <span className={cn('rounded-md px-2 py-0.5 font-medium', entry.reason_label ? 'bg-muted' : 'bg-amber-500/10 text-amber-700 dark:text-amber-300')}>{reason}</span>
          {entry.justification && <span className="text-muted-foreground">«{entry.justification}»</span>}
        </div>
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none hover:text-foreground">Detalle técnico</summary>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            <span>Confianza del valor original: {Math.round(entry.original_confidence * 100)} %</span>
            <span>Modelo: {entry.model_version ?? '—'}</span>
            <span>Instrucción: {entry.prompt_version?.slice(0, 7) ?? '—'}</span>
            <span>Campo: <code>{entry.field_path}</code></span>
          </div>
        </details>
      </div>
    </div>
  )
}

function Corrections() {
  const [limit, setLimit] = useState(100)
  const { data, isLoading, isError, isFetching } = useAuditLog({ limit })
  const { data: summary } = useCorrectionSummary()
  const typeName = useTypeName()
  const [reason, setReason] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const reasons = new Map<string, { total: number; types: string[] }>()
  for (const r of summary ?? []) {
    const entry = reasons.get(r.reason_label) ?? { total: 0, types: [] }
    entry.total += r.count
    entry.types.push(`${typeName(r.document_type)} (${r.count})`)
    reasons.set(r.reason_label, entry)
  }
  const total = [...reasons.values()].reduce((n, r) => n + r.total, 0)
  const q = query.trim().toLocaleLowerCase('es')
  const shown = (data?.entries ?? []).filter(
    (e) =>
      (!reason || (e.reason_label ?? NO_REASON) === reason) &&
      (!q || `${e.field_label ?? e.field_path} ${e.document_filename ?? ''} ${e.reviewer_identity} ${e.justification ?? ''}`.toLocaleLowerCase('es').includes(q)),
  )

  if (isLoading) return <Loader2 className="size-5 animate-spin text-muted-foreground" />
  if (isError) return <p className="text-sm text-muted-foreground">No se pudo cargar el historial: el servidor de Veritium no responde.</p>
  if (!data?.entries.length) return <p className="text-sm text-muted-foreground">Aún no se ha corregido ningún dato.</p>

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3 rounded-2xl border bg-muted/40 p-4 sm:p-5">
        <div className="flex flex-col">
          <h2 className="font-semibold">Por qué se corrige</h2>
          <p className="text-sm text-muted-foreground">{total === 1 ? '1 corrección' : `${total} correcciones`}. Elige un motivo para ver solo esas.</p>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {[...reasons.entries()]
            .sort((a, b) => b[1].total - a[1].total)
            .map(([label, r]) => {
              const active = reason === label
              const missing = label === NO_REASON
              return (
                <button key={label} type="button" onClick={() => setReason(active ? null : label)} className={cn('group flex flex-col gap-1 rounded-lg p-2 text-left transition hover:bg-background', active && 'bg-background ring-1 ring-primary')}>
                  <span className="flex items-center justify-between gap-3 text-sm">
                    <span className={cn('font-medium', missing && 'text-amber-700 dark:text-amber-300')}>{label}</span>
                    <span className="text-xs text-muted-foreground">{r.types.join(' · ')}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                      <span className={cn('block h-full rounded-full', missing ? 'bg-amber-500' : 'bg-primary')} style={{ width: `${(r.total / total) * 100}%` }} />
                    </span>
                    <span className="w-6 text-right text-sm font-semibold tabular-nums">{r.total}</span>
                  </span>
                </button>
              )
            })}
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-80">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar por dato, documento o revisor" className="pl-8" />
        </div>
        {(reason || q) && (
          <Button size="sm" variant="ghost" onClick={() => (setReason(null), setQuery(''))}>
            Ver todas
          </Button>
        )}
      </div>

      {shown.length ? (
        byDay(shown, (e) => e.timestamp).map((g) => (
          <Day key={g.day} day={g.day}>
            {g.items.map((e) => (
              <CorrectionRow key={e.id} entry={e} />
            ))}
          </Day>
        ))
      ) : (
        <p className="text-sm text-muted-foreground">Ninguna corrección coincide.</p>
      )}

      {data.total > data.entries.length && (
        <Button variant="outline" className="self-center" disabled={isFetching} onClick={() => setLimit(limit + 100)}>
          {isFetching && <Loader2 className="size-4 animate-spin" />} Ver anteriores ({data.total - data.entries.length} más)
        </Button>
      )}
    </div>
  )
}

function AccessRow({ entry }: { entry: DataAccessEntry }) {
  const meta = ACTION[entry.action]
  const Icon: LucideIcon = automatic(entry) ? Bot : (meta?.icon ?? FileText)
  return (
    <div className="flex items-start gap-3 p-4">
      <span className="w-16 shrink-0 pt-1 text-xs text-muted-foreground tabular-nums">{time(entry.at)}</span>
      <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', automatic(entry) ? 'bg-muted text-muted-foreground' : (meta?.tone ?? 'bg-muted'))}>
        <Icon className="size-4" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-sm">
        <span>
          <span className="font-medium">{automatic(entry) ? `Proceso automático (${entry.actor})` : entry.actor}</span> · {entry.action_label.toLowerCase()}{' '}
          <span className="text-muted-foreground">({entry.what})</span>
          {entry.case_id && (
            <>
              {' '}
              en{' '}
              <Link to={`/cases/${entry.case_id}`} className="text-primary hover:underline">
                {entry.case_ref ?? `expediente ${entry.case_id.slice(0, 8)}`}
              </Link>
            </>
          )}
        </span>
        <span className="text-xs text-muted-foreground">
          {entry.reason ? <>Para qué: «{entry.reason}»</> : 'Sin motivo indicado'}
          {!automatic(entry) && ` · ${entry.role}, ${CHANNEL[entry.channel] ?? entry.channel}`}
        </span>
      </div>
    </div>
  )
}

function Accesses() {
  const [limit, setLimit] = useState(500)
  const { data, isLoading, isError, isFetching } = useDataAccessLog(limit)
  const [who, setWho] = useState<'people' | 'automatic' | 'all'>('people')
  const [action, setAction] = useState<string | null>(null)
  const all = data ?? []
  const byWho = all.filter((e) => who === 'all' || (who === 'automatic') === automatic(e))
  const actions = [...new Map(byWho.map((e) => [e.action, e.action_label])).entries()]
  const shown = byWho.filter((e) => !action || e.action === action)
  const automaticCount = all.filter(automatic).length

  if (isLoading) return <Loader2 className="size-5 animate-spin text-muted-foreground" />
  if (isError) return <p className="text-sm text-muted-foreground">No se pudo cargar el registro: el servidor de Veritium no responde.</p>

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        Cada vez que alguien vio los datos personales de un expediente, descargó un original, buscó por un dato o los eliminó. El registro nunca guarda los
        datos.
      </p>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <Chip active={who === 'people'} onClick={() => (setWho('people'), setAction(null))}>
            Personas <span className="opacity-70">{all.length - automaticCount}</span>
          </Chip>
          <Chip active={who === 'automatic'} onClick={() => (setWho('automatic'), setAction(null))}>
            <Bot className="size-3" /> Procesos automáticos <span className="opacity-70">{automaticCount}</span>
          </Chip>
          <Chip active={who === 'all'} onClick={() => (setWho('all'), setAction(null))}>
            Todo <span className="opacity-70">{all.length}</span>
          </Chip>
        </div>
        {actions.length > 1 && (
          <div className="flex flex-wrap gap-2">
            {actions.map(([key, label]) => {
              const Icon = ACTION[key]?.icon ?? FileText
              return (
                <Chip key={key} active={action === key} onClick={() => setAction(action === key ? null : key)}>
                  <Icon className="size-3" /> {label} <span className="opacity-70">{byWho.filter((e) => e.action === key).length}</span>
                </Chip>
              )
            })}
          </div>
        )}
      </div>

      {shown.length ? (
        byDay(shown, (e) => e.at).map((g) => (
          <Day key={g.day} day={g.day}>
            {g.items.map((e) => (
              <AccessRow key={e.id} entry={e} />
            ))}
          </Day>
        ))
      ) : (
        <p className="text-sm text-muted-foreground">{who === 'people' ? 'Todavía ninguna persona pidió ver datos personales.' : 'No hay registros con este filtro.'}</p>
      )}

      {all.length === limit && (
        <Button variant="outline" className="self-center" disabled={isFetching} onClick={() => setLimit(limit + 500)}>
          {isFetching && <Loader2 className="size-4 animate-spin" />} Ver anteriores
        </Button>
      )}
    </div>
  )
}

export function AuditPage() {
  const admin = isAdmin()
  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Auditoría</h1>
        <p className="text-muted-foreground">Quién cambió un dato y por qué{admin && ', y quién vio los datos personales de un expediente'}.</p>
      </div>
      {admin ? (
        <Tabs defaultValue="corrections">
          <TabsList>
            <TabsTrigger value="corrections">Correcciones</TabsTrigger>
            <TabsTrigger value="access">Datos personales</TabsTrigger>
          </TabsList>
          <TabsContent value="corrections" className="pt-4">
            <Corrections />
          </TabsContent>
          <TabsContent value="access" className="pt-4">
            <Accesses />
          </TabsContent>
        </Tabs>
      ) : (
        <Corrections />
      )}
    </div>
  )
}
