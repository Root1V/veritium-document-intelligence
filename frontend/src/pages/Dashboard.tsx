// The home page answers "what do I do today, and how are we doing?" (VRT-74).
// Whoever works cases sees their work first; whoever supervises also sees
// each figure against the previous period and why cases don't decide themselves.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownRight, ArrowRight, ArrowUpRight, CircleCheck, CircleX, ClipboardCheck, FileWarning, Loader2, type LucideIcon } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { getUserName, getUserRole, isPlatformAdmin } from '@/lib/auth'
import { useOverview } from '@/lib/queries'
import { VERDICT_LABEL } from '@/lib/verdict'
import type { AttentionItem, Comparison, Overview } from '@/types/api'

const COLOR = { continued: '#10b981', human_review: '#f59e0b', return_to_client: '#ef4444', in_progress: '#94a3b8' } as const
const PERIODS = [7, 30] as const

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

function Tile({ label, value, children, tone }: { label: string; value: string; children?: React.ReactNode; tone?: 'warn' | 'bad' }) {
  return (
    <Card className={cn('gap-1 py-4', tone === 'warn' && 'border-amber-300 bg-amber-50 dark:bg-amber-950/30', tone === 'bad' && 'border-red-300 bg-red-50 dark:bg-red-950/30')}>
      <CardContent className="flex flex-col gap-1 px-4">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="text-3xl font-semibold tabular-nums tracking-tight">{value}</span>
        {children}
      </CardContent>
    </Card>
  )
}

const ATTENTION: Record<AttentionItem['kind'], { Icon: LucideIcon; className: string; action: string }> = {
  failed: { Icon: CircleX, className: 'text-red-600', action: 'Ver y reintentar' },
  review: { Icon: ClipboardCheck, className: 'text-amber-600', action: 'Revisar' },
  client: { Icon: FileWarning, className: 'text-sky-600', action: 'Ver' },
}

function Attention({ items }: { items: AttentionItem[] }) {
  return (
    <Card className="gap-0 py-0">
      <CardHeader className="border-b py-4">
        <CardTitle className="text-base">Requiere atención</CardTitle>
        <CardDescription>Lo que no se resolvió solo, lo más urgente primero.</CardDescription>
      </CardHeader>
      {items.length === 0 ? (
        <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <CircleCheck className="size-5 text-emerald-600" /> Nada requiere atención ahora.
        </CardContent>
      ) : (
        <ul className="divide-y">
          {items.map((item) => {
            const { Icon, className, action } = ATTENTION[item.kind]
            return (
              <li key={`${item.kind}-${item.case_id}`} className="flex items-center gap-3 px-6 py-3">
                <Icon className={cn('size-5 shrink-0', className)} aria-hidden />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-medium">{item.title}</span>
                  <span className="text-xs text-muted-foreground">
                    Expediente {item.case_ref} · {ago(item.since)}
                  </span>
                </div>
                <Button asChild size="sm" variant="outline">
                  <Link to={`/cases/${item.case_id}`}>{action}</Link>
                </Button>
              </li>
            )
          })}
        </ul>
      )}
      <div className="border-t px-6 py-3">
        <Link to="/cases" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
          Ver todos los expedientes <ArrowRight className="size-3.5" />
        </Link>
      </div>
    </Card>
  )
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
      {(['continued', 'human_review', 'return_to_client', 'in_progress'] as const).map((k) => (
        <span key={k} className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: COLOR[k] }} />
          {k === 'continued' ? VERDICT_LABEL.continue : k === 'in_progress' ? 'En curso' : VERDICT_LABEL[k]}
        </span>
      ))}
    </div>
  )
}

function Charts({ data }: { data: Overview }) {
  const daily = data.daily.map((d) => ({
    ...d,
    label: new Date(`${d.day}T12:00:00`).toLocaleDateString('es', data.days > 7 ? { day: 'numeric', month: 'short' } : { weekday: 'short', day: 'numeric' }),
  }))
  const tooltipStyle = { borderRadius: 8, border: '1px solid var(--border)', background: 'var(--popover)', fontSize: 12 }
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
      <Card className="xl:col-span-3">
        <CardHeader>
          <CardTitle className="text-base">Expedientes por día</CardTitle>
          <CardDescription>Los que llegaron cada día, según su decisión actual.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Legend />
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={daily} margin={{ left: -20, right: 8 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} interval="preserveStartEnd" />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'var(--muted)' }} />
                <Bar dataKey="continued" name={VERDICT_LABEL.continue} stackId="a" fill={COLOR.continued} maxBarSize={28} />
                <Bar dataKey="human_review" name={VERDICT_LABEL.human_review} stackId="a" fill={COLOR.human_review} maxBarSize={28} />
                <Bar dataKey="return_to_client" name={VERDICT_LABEL.return_to_client} stackId="a" fill={COLOR.return_to_client} maxBarSize={28} />
                <Bar dataKey="in_progress" name="En curso" stackId="a" fill={COLOR.in_progress} maxBarSize={28} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
      <Card className="xl:col-span-2">
        <CardHeader>
          <CardTitle className="text-base">Por qué no se resuelven solos</CardTitle>
          <CardDescription>Los motivos más frecuentes del periodo. Atacarlos es lo que más tiempo ahorra.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.reasons.length === 0 ? (
            <p className="text-sm text-muted-foreground">Ningún expediente del periodo quedó pendiente.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {data.reasons.map((r) => {
                const max = data.reasons[0].count
                return (
                  <li key={`${r.decision}-${r.label}`} className="flex flex-col gap-1">
                    <div className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="min-w-0 truncate" title={r.label}>
                        {r.label}
                      </span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">{r.count}</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted">
                      <div
                        className="h-2 rounded-full"
                        style={{ width: `${(r.count / max) * 100}%`, background: r.decision === 'return_to_client' ? COLOR.return_to_client : COLOR.human_review }}
                        title={VERDICT_LABEL[r.decision]}
                      />
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </CardContent>
      </Card>
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
  const [days, setDays] = useState<number>(7)
  const { data, isLoading } = useOverview(days)

  if (isLoading || !data) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }
  const percent = (v: number | null) => (v == null ? '—' : `${Math.round(v * 100)}%`)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{greeting()}</h1>
          <p className="text-muted-foreground">
            <Summary data={data} />
          </p>
        </div>
        {supervises && (
          <div className="flex rounded-md border p-0.5" role="group" aria-label="Periodo">
            {PERIODS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setDays(p)}
                aria-pressed={days === p}
                className={cn('rounded px-3 py-1 text-sm', days === p ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}
              >
                Últimos {p} días
              </button>
            ))}
          </div>
        )}
      </div>

      {supervises ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Expedientes recibidos" value={String(data.received.value ?? 0)}>
            <Delta c={data.received} better="none" format={(d) => String(Math.round(d))} />
          </Tile>
          <Tile label="Resueltos sin intervención" value={percent(data.straight_through.value)}>
            <span className="text-xs text-muted-foreground">de {data.decided} con decisión</span>
            <Delta c={data.straight_through} better="up" format={(d) => `${Math.round(d * 100)} pts`} />
          </Tile>
          <Tile label="Tiempo hasta decidir" value={duration(data.time_to_verdict_seconds.value)}>
            <span className="text-xs text-muted-foreground">mediana desde que llega</span>
            <Delta c={data.time_to_verdict_seconds} better="down" format={(d) => duration(d)} />
          </Tile>
          <Tile label="Campos por revisar" value={String(data.pending_review)} tone={data.pending_review > 0 ? 'warn' : undefined}>
            <span className="text-xs text-muted-foreground">{data.oldest_pending ? `el más antiguo ${ago(data.oldest_pending)}` : 'al día'}</span>
          </Tile>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Campos por revisar" value={String(data.pending_review)} tone={data.pending_review > 0 ? 'warn' : undefined}>
            <span className="text-xs text-muted-foreground">{data.oldest_pending ? `el más antiguo ${ago(data.oldest_pending)}` : 'al día'}</span>
          </Tile>
          <Tile label="Expedientes en revisión" value={String(data.in_review)} />
          <Tile label="Esperan documentos del cliente" value={String(data.waiting_client)} />
          <Tile label="Documentos que no se pudieron leer" value={String(data.failed_documents)} tone={data.failed_documents > 0 ? 'bad' : undefined} />
        </div>
      )}

      <Attention items={data.attention} />
      {supervises && <Charts data={data} />}
    </div>
  )
}
