// The home page answers "what do I do today, and how are we doing?" (VRT-74,
// VRT-111). First, what to look at — a few conclusions drawn from the figures,
// each with where to act; then the figures against the previous period; then
// where the work is: cases per day, how they end and by which channel, why
// they do not decide themselves, which documents need a person most, and how
// long the review queue has waited; last, what needs a person now.
// Decision colors are the status palette — always beside their label.
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CircleCheck,
  CircleX,
  ClipboardCheck,
  FileWarning,
  Hourglass,
  Lightbulb,
  Loader2,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react'
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/ui/button'
import { getUserName, getUserRole, isPlatformAdmin } from '@/lib/auth'
import { useTypeName } from '@/lib/labels'
import { useOverview } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { VERDICT_LABEL } from '@/lib/verdict'
import type { AttentionItem, Comparison, Overview } from '@/types/api'

// The status palette (good / warning / critical) and a neutral for what is still running.
const DECISIONS = [
  { key: 'continued', label: VERDICT_LABEL.continue, color: '#0ca30c' },
  { key: 'human_review', label: VERDICT_LABEL.human_review, color: '#fab219' },
  { key: 'return_to_client', label: VERDICT_LABEL.return_to_client, color: '#d03b3b' },
  { key: 'in_progress', label: 'En curso', color: '#94a3b8' },
] as const
type DecisionKey = (typeof DECISIONS)[number]['key']
// An ordinal one-hue ramp for how long the queue has waited: older, darker.
const AGE_RAMP = ['#86b6ef', '#3987e5', '#256abf', '#184f95'] // validated ordinal, light and dark
const PERIODS = [7, 30, 90] as const
const CHANNEL_LABEL: Record<string, string> = { online: 'En línea', backoffice: 'Oficina', bulk: 'Carga masiva' }

function greeting(): string {
  const hour = new Date().getHours()
  const first = (getUserName() ?? '').split(' ')[0]
  return `${hour < 12 ? 'Buenos días' : hour < 19 ? 'Buenas tardes' : 'Buenas noches'}${first ? `, ${first}` : ''}`
}

function ago(iso: string | null): string {
  if (!iso) return ''
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  const rtf = new Intl.RelativeTimeFormat('es', { numeric: 'auto' })
  if (minutes < 60) return rtf.format(-minutes, 'minute')
  if (minutes < 60 * 24) return rtf.format(-Math.round(minutes / 60), 'hour')
  return rtf.format(-Math.round(minutes / 60 / 24), 'day')
}

function duration(seconds: number | null): string {
  if (seconds == null) return '—'
  if (seconds < 90) return `${Math.round(seconds)} s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 90) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  return `${hours} h ${minutes % 60} min`
}

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const sum = (o: Record<DecisionKey, number>) => DECISIONS.reduce((n, d) => n + o[d.key], 0)

/** The change against the previous period, colored by whether it is good news. */
function Delta({ c, better, format }: { c: Comparison; better: 'up' | 'down' | 'none'; format: (d: number) => string }) {
  if (c.value == null || c.previous == null) return <span className="text-xs text-muted-foreground">sin periodo anterior para comparar</span>
  const d = c.value - c.previous
  if (Math.abs(d) < 1e-9) return <span className="text-xs text-muted-foreground">igual que el periodo anterior</span>
  const good = better === 'none' ? null : (d > 0) === (better === 'up')
  const Icon = d > 0 ? ArrowUpRight : ArrowDownRight
  return (
    <span className={cn('inline-flex items-center gap-0.5 text-xs', good == null ? 'text-muted-foreground' : good ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400')}>
      <Icon className="size-3.5" />
      {format(Math.abs(d))} vs. periodo anterior
    </span>
  )
}

function Tile({ label, value, children, tone, trend, color = 'var(--series-1)' }: { label: string; value: string; children?: ReactNode; tone?: 'warn' | 'bad'; trend?: number[]; color?: string }) {
  return (
    <div className={cn('flex flex-col gap-1 rounded-xl border bg-card p-4', tone === 'warn' && 'border-amber-500/40 bg-amber-500/5', tone === 'bad' && 'border-red-500/40 bg-red-500/5')}>
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-3xl font-semibold tracking-tight tabular-nums">{value}</span>
      {children}
      {trend && <Sparkline values={trend} color={color} />}
    </div>
  )
}

function Panel({ title, hint, children, className }: { title: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('flex flex-col gap-3 rounded-xl border bg-card p-4', className)}>
      <div className="flex flex-col">
        <h2 className="font-semibold">{title}</h2>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      </div>
      {children}
    </section>
  )
}

/** A one-line trend for a tile: no axes, just its shape. */
function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.every((v) => v === 0)) return null
  const id = `spark-${color.replace(/[^a-z0-9]/gi, '')}`
  return (
    <div className="h-9">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={values.map((v, i) => ({ i, v }))} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#${id})`} isAnimationActive={false} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

/** A ring of decisions with its total in the middle; each slice says itself on hover. */
function DecisionRing({ counts, size, label }: { counts: Record<DecisionKey, number>; size: number; label?: string }) {
  const total = sum(counts)
  const slices = DECISIONS.filter((d) => counts[d.key]).map((d) => ({ name: d.label, value: counts[d.key], color: d.color }))
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={slices} dataKey="value" innerRadius="70%" outerRadius="100%" paddingAngle={slices.length > 1 ? 2 : 0} stroke="none" isAnimationActive={false}>
            {slices.map((sl) => (
              <Cell key={sl.name} fill={sl.color} />
            ))}
          </Pie>
          <Tooltip content={<RingTip total={total} />} />
        </PieChart>
      </ResponsiveContainer>
      <span className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn('font-semibold tabular-nums', size > 100 ? 'text-2xl' : 'text-sm')}>{total}</span>
        {label && <span className="text-[10px] text-muted-foreground">{label}</span>}
      </span>
    </div>
  )
}

function RingTip({ active, payload, total }: { active?: boolean; payload?: { name: string; value: number; payload: { color: string } }[]; total: number }) {
  if (!active || !payload?.length) return null
  const p = payload[0]
  return (
    <div className="rounded-lg border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-sm">
      <span className="inline-flex items-center gap-1.5">
        <span className="size-2 rounded-full" style={{ background: p.payload.color }} /> {p.name}: <strong>{p.value}</strong> ({pct(p.value / Math.max(total, 1))})
      </span>
    </div>
  )
}

/** One share as a ring: how much of a whole, at a glance. */
function PercentRing({ value, color, size = 44 }: { value: number; color: string; size?: number }) {
  const r = (size - 6) / 2
  const c = 2 * Math.PI * r
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0 -rotate-90" aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--muted)" strokeWidth={5} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={5} strokeLinecap="round" strokeDasharray={`${c * Math.min(value, 1)} ${c}`} />
    </svg>
  )
}


interface Insight {
  tone: 'good' | 'warn' | 'bad' | 'info'
  icon: LucideIcon
  text: ReactNode
  action?: { label: string; to?: string; onClick?: () => void }
}

const TONE = {
  good: 'border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400',
  warn: 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400',
  bad: 'border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400',
  info: 'border-sky-500/40 bg-sky-500/5 text-sky-700 dark:text-sky-400',
} as const

/** Conclusions drawn from the figures, the most pressing first — each with where to act. */
function insightsOf(data: Overview, typeName: (k: string | null) => string, setDays: (d: number) => void): Insight[] {
  const out: Insight[] = []
  const totals = data.daily.reduce<Record<DecisionKey, number>>(
    (acc, d) => ({ continued: acc.continued + d.continued, human_review: acc.human_review + d.human_review, return_to_client: acc.return_to_client + d.return_to_client, in_progress: acc.in_progress + d.in_progress }),
    { continued: 0, human_review: 0, return_to_client: 0, in_progress: 0 },
  )
  const decided = totals.continued + totals.human_review + totals.return_to_client
  const old = data.backlog.find((b) => b.label === 'Más de 30 días')?.count ?? 0

  if (!data.received.value) {
    const longer = PERIODS.find((p) => p > data.days)
    out.push({
      tone: 'info',
      icon: Lightbulb,
      text: <>No llegaron expedientes en los últimos {data.days} días.</>,
      action: longer ? { label: `Ver los últimos ${longer} días`, onClick: () => setDays(longer) } : undefined,
    })
  }
  if (old > 0)
    out.push({
      tone: 'bad',
      icon: Hourglass,
      text: (
        <>
          <strong>{old === 1 ? '1 dato lleva' : `${old} datos llevan`} más de un mes</strong> esperando revisión: sus expedientes no pueden decidirse.
        </>
      ),
      action: { label: 'Revisarlos', to: '/review' },
    })
  if (decided >= 3 && totals.return_to_client / decided >= 0.3) {
    const why = data.reasons.find((r) => r.decision === 'return_to_client')
    out.push({
      tone: 'warn',
      icon: FileWarning,
      text: (
        <>
          <strong>{Math.round((10 * totals.return_to_client) / decided)} de cada 10</strong> expedientes se devuelven al cliente
          {why && (
            <>
              ; el motivo más común: «{why.label}» ({why.count})
            </>
          )}
          . Pedirlo bien desde el inicio ahorra idas y vueltas.
        </>
      ),
      action: { label: 'Ver expedientes', to: '/cases' },
    })
  }
  const top = data.reasons[0]
  if (top && top.decision === 'human_review')
    out.push({
      tone: 'warn',
      icon: AlertTriangle,
      text: (
        <>
          Lo que más frena a los expedientes: <strong>«{top.label}»</strong> ({top.count}). Corregir su causa es lo que más trabajo ahorra.
        </>
      ),
      action: { label: 'Ver observaciones', to: '/validation' },
    })
  const worst = data.by_document_type.filter((t) => t.documents >= 3).sort((a, b) => b.needs_review / b.documents - a.needs_review / a.documents)[0]
  if (worst && worst.needs_review / worst.documents >= 0.25)
    out.push({
      tone: 'warn',
      icon: ClipboardCheck,
      text: (
        <>
          <strong>{typeName(worst.document_type)}</strong> es lo que más revisión pide: {pct(worst.needs_review / worst.documents)} de sus documentos necesitó a una
          persona.
        </>
      ),
      action: { label: 'Ver confiabilidad', to: '/calibration' },
    })
  const st = data.straight_through
  if (st.value != null && st.previous != null && Math.abs(st.value - st.previous) >= 0.05) {
    const up = st.value > st.previous
    out.push({
      tone: up ? 'good' : 'bad',
      icon: up ? TrendingUp : TrendingDown,
      text: (
        <>
          Los resueltos sin intervención {up ? 'subieron' : 'bajaron'} de {pct(st.previous)} a <strong>{pct(st.value)}</strong> frente al periodo anterior.
        </>
      ),
    })
  }
  if (data.failed_documents > 0)
    out.push({
      tone: 'bad',
      icon: CircleX,
      text: (
        <>
          <strong>{data.failed_documents === 1 ? '1 documento no se pudo leer' : `${data.failed_documents} documentos no se pudieron leer`}</strong>: reintentarlos o pedir otra
          copia.
        </>
      ),
      action: { label: 'Ver cuáles', to: '#atencion' },
    })
  return out.slice(0, 4)
}

function Insights({ items }: { items: Insight[] }) {
  if (!items.length)
    return (
      <div className="flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-400">
        <CircleCheck className="size-4" /> Todo en orden: nada pide una decisión ahora.
      </div>
    )
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-semibold">Para decidir hoy</h2>
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((it, i) => (
          <div key={i} className={cn('flex items-start gap-3 rounded-xl border px-4 py-3', TONE[it.tone])}>
            <it.icon className="mt-0.5 size-4 shrink-0" />
            <span className="flex-1 text-sm text-foreground">{it.text}</span>
            {it.action &&
              (it.action.to?.startsWith('#') ? (
                <a href={it.action.to} className="shrink-0 text-sm font-medium hover:underline">
                  {it.action.label}
                </a>
              ) : it.action.to ? (
                <Link to={it.action.to} className="inline-flex shrink-0 items-center gap-1 text-sm font-medium hover:underline">
                  {it.action.label} <ArrowRight className="size-3.5" />
                </Link>
              ) : (
                <button type="button" onClick={it.action.onClick} className="shrink-0 text-sm font-medium hover:underline">
                  {it.action.label}
                </button>
              ))}
          </div>
        ))}
      </div>
    </section>
  )
}

const ATTENTION: Record<AttentionItem['kind'], { Icon: LucideIcon; className: string; action: string }> = {
  failed: { Icon: CircleX, className: 'text-red-600', action: 'Ver y reintentar' },
  review: { Icon: ClipboardCheck, className: 'text-amber-600', action: 'Revisar' },
  client: { Icon: FileWarning, className: 'text-sky-600', action: 'Ver' },
}

function Attention({ items }: { items: AttentionItem[] }) {
  return (
    <section id="atencion" className="flex scroll-mt-20 flex-col overflow-hidden rounded-xl border bg-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b px-4 py-3">
        <div className="flex flex-col">
          <h2 className="font-semibold">Requiere atención</h2>
          <span className="text-xs text-muted-foreground">Lo que no se resolvió solo, lo más urgente primero.</span>
        </div>
        <Link to="/cases" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
          Ver todos los expedientes <ArrowRight className="size-3.5" />
        </Link>
      </div>
      {items.length === 0 ? (
        <div className="flex items-center gap-2 px-4 py-5 text-sm text-muted-foreground">
          <CircleCheck className="size-5 text-emerald-600" /> Nada requiere atención ahora.
        </div>
      ) : (
        <ul className="grid md:grid-cols-2">
          {items.map((item) => {
            const { Icon, className, action } = ATTENTION[item.kind]
            return (
              <li key={`${item.kind}-${item.case_id}`} className="flex items-center gap-3 border-b px-4 py-2.5 md:odd:border-r">
                <Icon className={cn('size-4 shrink-0', className)} aria-hidden />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-medium">{item.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {item.case_ref} · {ago(item.since)}
                  </span>
                </div>
                <Button asChild size="sm" variant="ghost" className="h-7 shrink-0">
                  <Link to={`/cases/${item.case_id}`}>{action}</Link>
                </Button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

// Lines cross: identity takes the first three categorical slots, validated all-pairs in light and dark.
const SERIES = [
  { key: 'received', label: 'Recibidos', color: 'var(--series-1)' },
  { key: 'pending', label: 'Pendientes (revisión o cliente)', color: 'var(--series-2)' },
  { key: 'continued', label: 'Continuar', color: 'var(--series-3)' },
] as const
type SeriesKey = (typeof SERIES)[number]['key']

function TrendTip({ active, label, payload }: { active?: boolean; label?: string; payload?: { dataKey: string; value: number; color: string; name: string }[] }) {
  if (!active || !payload?.length) return null
  return (
    <div className="flex flex-col gap-1 rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <span className="font-medium">{label}</span>
      {payload.map((p) => (
        <span key={p.dataKey} className="flex items-center justify-between gap-4">
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: p.color }} /> {p.name}
          </span>
          <strong className="tabular-nums">{p.value}</strong>
        </span>
      ))}
    </div>
  )
}

/** Cases per day as smooth lines, one per series, on one scale; a crosshair says the day's values. */
function Trend({ data }: { data: Overview }) {
  const [hidden, setHidden] = useState<SeriesKey[]>([])
  const rows = data.daily.map((d) => ({
    label: new Date(`${d.day}T12:00:00`).toLocaleDateString('es', { day: 'numeric', month: 'short' }),
    received: d.continued + d.human_review + d.return_to_client + d.in_progress,
    pending: d.human_review + d.return_to_client,
    continued: d.continued,
  }))
  const shown = SERIES.filter((s) => !hidden.includes(s.key))
  return (
    <Panel title="Tendencia" hint={`Por día de llegada, en los últimos ${data.days} días: cuántos llegaron, cuántos siguen pendientes y cuántos continuaron. Pasa el cursor para ver cada día.`}>
      <div className="flex flex-wrap gap-2">
        {SERIES.map((s) => {
          const on = !hidden.includes(s.key)
          return (
            <button
              key={s.key}
              type="button"
              aria-pressed={on}
              onClick={() => setHidden(on ? [...hidden, s.key] : hidden.filter((k) => k !== s.key))}
              className={cn('inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition', on ? 'bg-card' : 'opacity-50')}
            >
              <span className="size-2 rounded-full" style={{ background: s.color }} /> {s.label}
            </button>
          )
        })}
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ left: -20, right: 8, top: 8 }}>
            <defs>
              {SERIES.map((s) => (
                <linearGradient key={s.key} id={`trend-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={s.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} interval="preserveStartEnd" minTickGap={24} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={11} />
            <Tooltip content={<TrendTip />} cursor={{ stroke: 'var(--muted-foreground)', strokeWidth: 1 }} />
            {shown.map((s) => (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color}
                strokeWidth={2}
                fill={`url(#trend-${s.key})`}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  )
}

function Charts({ data, typeName }: { data: Overview; typeName: (k: string | null) => string }) {
  const totals = data.daily.reduce<Record<DecisionKey, number>>(
    (acc, d) => ({ continued: acc.continued + d.continued, human_review: acc.human_review + d.human_review, return_to_client: acc.return_to_client + d.return_to_client, in_progress: acc.in_progress + d.in_progress }),
    { continued: 0, human_review: 0, return_to_client: 0, in_progress: 0 },
  )
  const total = sum(totals)
  const types = [...data.by_document_type].sort((a, b) => (b.needs_review + b.failed) / b.documents - (a.needs_review + a.failed) / a.documents).slice(0, 6)

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Trend data={data} />
        </div>
        <Panel title="Cómo terminan" hint={`Los ${total} expedientes del periodo, y por canal.`}>
          {total === 0 ? (
            <p className="text-sm text-muted-foreground">Ningún expediente en el periodo.</p>
          ) : (
            <>
              <div className="flex items-center gap-4">
                <DecisionRing counts={totals} size={120} label="expedientes" />
                <div className="flex flex-1 flex-col gap-1.5">
                  {DECISIONS.map((d) => (
                    <span key={d.key} className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                        <span className="size-2.5 rounded-full" style={{ background: d.color }} /> {d.label}
                      </span>
                      <span className="tabular-nums">
                        <strong>{totals[d.key]}</strong> <span className="text-xs text-muted-foreground">{pct(totals[d.key] / total)}</span>
                      </span>
                    </span>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2 border-t pt-3">
                {data.by_channel.map((c) => (
                  <div key={c.channel} className="flex flex-col items-center gap-1">
                    <DecisionRing counts={c} size={56} />
                    <span className="text-center text-xs text-muted-foreground">{CHANNEL_LABEL[c.channel] ?? c.channel}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Por qué no se resuelven solos" hint="Los motivos más frecuentes del periodo.">
          {data.reasons.length === 0 ? (
            <p className="text-sm text-muted-foreground">Ningún expediente del periodo quedó pendiente.</p>
          ) : (
            <ol className="flex flex-col divide-y">
              {data.reasons.map((r, i) => {
                const d = r.decision === 'return_to_client' ? DECISIONS[2] : DECISIONS[1]
                return (
                  <li key={`${r.decision}-${r.label}`} className="flex items-center gap-3 py-2 text-sm">
                    <span className="w-4 shrink-0 text-xs text-muted-foreground tabular-nums">{i + 1}</span>
                    <span className="size-2 shrink-0 rounded-full" style={{ background: d.color }} title={d.label} />
                    <span className="min-w-0 flex-1 truncate" title={r.label}>
                      {r.label}
                    </span>
                    <span className="shrink-0 font-semibold tabular-nums">{r.count}</span>
                  </li>
                )
              })}
            </ol>
          )}
        </Panel>

        <Panel title="Documentos que más revisión piden" hint="Qué parte de cada tipo necesitó a una persona o no se pudo leer.">
          {types.length === 0 ? (
            <p className="text-sm text-muted-foreground">Ningún documento en el periodo.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {types.map((t) => {
                const share = (t.needs_review + t.failed) / t.documents
                const color = share >= 0.5 ? DECISIONS[2].color : share >= 0.15 ? DECISIONS[1].color : DECISIONS[0].color
                return (
                  <li
                    key={t.document_type ?? 'none'}
                    className="flex items-center gap-2.5"
                    title={`${typeName(t.document_type)}: ${t.documents} documentos · ${t.needs_review} con revisión · ${t.failed} sin leer`}
                  >
                    <span className="relative flex items-center justify-center">
                      <PercentRing value={share} color={color} size={40} />
                      <span className="absolute text-[10px] font-semibold tabular-nums">{Math.round(share * 100)}%</span>
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate text-sm">{typeName(t.document_type)}</span>
                      <span className="text-xs text-muted-foreground">
                        {t.needs_review + t.failed} de {t.documents}
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </Panel>

        <Panel title="Cuánto espera la cola de revisión" hint={`Los ${data.pending_review} datos que esperan a una persona, por antigüedad.`}>
          <div className="grid grid-cols-2 gap-3">
            {data.backlog.map((b, i) => (
              <div key={b.label} className="flex flex-col gap-0.5 rounded-lg border-l-4 bg-muted/40 px-3 py-2" style={{ borderLeftColor: AGE_RAMP[i] }}>
                <span className={cn('text-2xl font-semibold tabular-nums', i === 3 && b.count > 0 && 'text-red-700 dark:text-red-400')}>{b.count}</span>
                <span className="text-xs text-muted-foreground">{b.label}</span>
              </div>
            ))}
          </div>
          {data.pending_review > 0 && (
            <Link to="/review" className="inline-flex w-fit items-center gap-1 text-sm text-primary hover:underline">
              Ir a la cola <ArrowRight className="size-3.5" />
            </Link>
          )}
        </Panel>
      </div>
    </div>
  )
}


function Summary({ data }: { data: Overview }) {
  const parts = [
    data.in_review && `${data.in_review} ${data.in_review === 1 ? 'expediente está' : 'expedientes están'} en revisión`,
    data.waiting_client && `${data.waiting_client} ${data.waiting_client === 1 ? 'espera' : 'esperan'} documentos del cliente`,
    data.failed_documents && `${data.failed_documents} ${data.failed_documents === 1 ? 'documento no se pudo leer' : 'documentos no se pudieron leer'}`,
  ].filter(Boolean)
  if (parts.length === 0) return <>Nada requiere atención. Así va la unidad.</>
  return <>{parts.join(' · ')}.</>
}

export function DashboardPage() {
  const role = getUserRole()
  const supervises = role !== 'operador' || isPlatformAdmin()
  const [days, setDays] = useState<number>(30)
  const { data, isLoading, isError } = useOverview(days)
  const typeName = useTypeName()

  if (isError) return <p className="text-sm text-muted-foreground">No se pudo cargar el inicio: el servidor de Veritium no responde.</p>
  if (isLoading || !data) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="viz-root flex flex-col gap-6">
      <style>{`.viz-root{--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a}.dark .viz-root{--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70}`}</style>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{greeting()}</h1>
          <p className="text-muted-foreground">
            <Summary data={data} />
          </p>
        </div>
        {supervises && (
          <div className="flex rounded-lg border p-0.5" role="group" aria-label="Periodo">
            {PERIODS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setDays(p)}
                aria-pressed={days === p}
                className={cn('rounded-md px-3 py-1 text-sm', days === p ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}
              >
                {p} días
              </button>
            ))}
          </div>
        )}
      </div>

      <Insights items={insightsOf(data, typeName, setDays)} />

      {supervises ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Expedientes recibidos" value={String(data.received.value ?? 0)} trend={data.daily.map((d) => d.continued + d.human_review + d.return_to_client + d.in_progress)}>
            <Delta c={data.received} better="none" format={(d) => String(Math.round(d))} />
          </Tile>
          <Tile label="Resueltos sin intervención" value={pct(data.straight_through.value)} trend={data.daily.map((d) => d.continued)} color="var(--series-3)">
            <span className="text-xs text-muted-foreground">de {data.decided} con decisión</span>
            <Delta c={data.straight_through} better="up" format={(d) => `${Math.round(d * 100)} pts`} />
          </Tile>
          <Tile label="Tiempo hasta decidir" value={duration(data.time_to_verdict_seconds.value)}>
            <span className="text-xs text-muted-foreground">mediana desde que llega</span>
            <Delta c={data.time_to_verdict_seconds} better="down" format={(d) => duration(d)} />
          </Tile>
          <Tile label="Datos por revisar" value={String(data.pending_review)} tone={data.pending_review > 0 ? 'warn' : undefined}>
            <span className="text-xs text-muted-foreground">{data.oldest_pending ? `el más antiguo ${ago(data.oldest_pending)}` : 'al día'}</span>
          </Tile>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Datos por revisar" value={String(data.pending_review)} tone={data.pending_review > 0 ? 'warn' : undefined}>
            <span className="text-xs text-muted-foreground">{data.oldest_pending ? `el más antiguo ${ago(data.oldest_pending)}` : 'al día'}</span>
          </Tile>
          <Tile label="Expedientes en revisión" value={String(data.in_review)} />
          <Tile label="Esperan documentos del cliente" value={String(data.waiting_client)} />
          <Tile label="Documentos que no se pudieron leer" value={String(data.failed_documents)} tone={data.failed_documents > 0 ? 'bad' : undefined} />
        </div>
      )}

      {supervises && <Charts data={data} typeName={typeName} />}
      <Attention items={data.attention} />
    </div>
  )
}
