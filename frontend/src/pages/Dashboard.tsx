import { Link } from 'react-router-dom'
import { ClipboardCheck, Clock, FileText, Loader2, Sparkles, Upload, Compass } from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { useDocumentList, useReviewQueue, useTypeSuggestions } from '@/lib/queries'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { canExecute, getUserName } from '@/lib/auth'
import { StatusBadge } from '@/components/StatusBadge'
import { useTypeName } from '@/lib/labels'

const CHART_COLORS = ['#7c3aed', '#a78bfa', '#c4b5fd', '#f59e0b', '#10b981', '#3b82f6', '#ec4899', '#6b7280']

// Asunción explícita y configurable (no un dato medido) — ver .env.example.
const ASSUMED_MINUTES_PER_DOCUMENT = Number(import.meta.env.VITE_ASSUMED_MINUTES_PER_DOCUMENT ?? 8)

function formatHours(totalMinutes: number): string {
  const hours = totalMinutes / 60
  return hours >= 10 ? `${hours.toFixed(0)} h` : `${hours.toFixed(1)} h`
}

function StatCard({
  label,
  value,
  icon: Icon,
  to,
  hint,
}: {
  label: string
  value: number | string
  icon: typeof FileText
  to?: string
  hint?: string
}) {
  const content = (
    <Card className="transition-colors hover:border-primary/40" title={hint}>
      <CardContent className="flex items-center gap-4 p-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
          <Icon className="size-5" />
        </div>
        <div>
          <div className="text-2xl font-semibold leading-tight">{value}</div>
          <div className="text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  )
  return to ? <Link to={to}>{content}</Link> : content
}

export function DashboardPage() {
  const typeName = useTypeName()
  const { data: documentList, isLoading } = useDocumentList({ limit: 20 })
  const { data: needsReviewCount } = useDocumentList({ needs_review: true, limit: 1 })
  const { data: completedCount } = useDocumentList({ status: 'completed', limit: 1 })
  const { data: reviewQueue } = useReviewQueue()
  const { data: typeSuggestions } = useTypeSuggestions()

  const timeSavedMinutes = (completedCount?.total ?? 0) * ASSUMED_MINUTES_PER_DOCUMENT

  const recentDocuments = (documentList?.documents ?? []).filter((doc) => doc.status !== 'segmented').slice(0, 10)

  const typeCounts = new Map<string, number>()
  for (const doc of documentList?.documents ?? []) {
    if (!doc.document_type) continue
    typeCounts.set(doc.document_type, (typeCounts.get(doc.document_type) ?? 0) + 1)
  }
  const chartData = [...typeCounts.entries()].map(([key, value]) => ({ name: typeName(key), value }))

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Hola, {getUserName() ?? ''} 👋</h1>
        <p className="text-muted-foreground">Aquí tienes un resumen de tu plataforma documental.</p>
      </div>

      {documentList?.total === 0 && (
        // A unit that has not processed anything yet: where to start (VRT-71).
        <Link to="/primeros-pasos" className="flex items-center gap-3 rounded-lg border border-primary/40 bg-primary/5 p-4 text-sm hover:bg-primary/10">
          <Compass className="size-5 text-primary" />
          <span>
            <span className="font-medium">Tu unidad todavía no tiene expedientes.</span> Empieza por los primeros pasos: qué preparar y en qué orden.
          </span>
        </Link>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <StatCard label="Documentos" value={documentList?.total ?? '—'} icon={FileText} />
        <StatCard label="Necesitan revisión" value={needsReviewCount?.total ?? '—'} icon={ClipboardCheck} to="/review" />
        <StatCard label="Revisiones pendientes" value={reviewQueue?.length ?? '—'} icon={ClipboardCheck} to="/review" />
        <StatCard label="Sugerencias de tipo" value={typeSuggestions?.length ?? '—'} icon={Sparkles} to="/type-suggestions" />
        <StatCard
          label="Tiempo ahorrado (estimado)"
          value={completedCount ? formatHours(timeSavedMinutes) : '—'}
          icon={Clock}
          hint={`Asume ${ASSUMED_MINUTES_PER_DOCUMENT} min/documento manual (VITE_ASSUMED_MINUTES_PER_DOCUMENT) × ${completedCount?.total ?? 0} documentos completados`}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Documentos recientes</CardTitle>
            {canExecute() && (
              <Link to="/upload" className="flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
                <Upload className="size-3.5" />
                Subir documentos
              </Link>
            )}
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex h-32 items-center justify-center">
                <Loader2 className="size-5 animate-spin text-muted-foreground" />
              </div>
            ) : recentDocuments.length === 0 ? (
              <p className="text-sm text-muted-foreground">Aún no hay documentos procesados.</p>
            ) : (
              <ul className="flex flex-col gap-1">
                {recentDocuments.map((doc) => (
                  <li key={doc.id}>
                    <Link
                      to={`/documents/${doc.id}`}
                      className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm transition-colors hover:bg-accent"
                    >
                      <FileText className="size-4 shrink-0 text-muted-foreground" />
                      <span className="flex-1 truncate">{doc.original_filename}</span>
                      <span className="text-xs text-muted-foreground">{typeName(doc.document_type)}</span>
                      <StatusBadge status={doc.needs_review ? 'needs_review' : doc.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Tipos de documento</CardTitle>
          </CardHeader>
          <CardContent>
            {chartData.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin datos todavía.</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={chartData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={2}>
                    {chartData.map((entry, index) => (
                      <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            )}
            <ul className="mt-2 flex flex-col gap-1">
              {chartData.map((entry, index) => (
                <li key={entry.name} className="flex items-center gap-2 text-xs">
                  <span
                    className="size-2.5 rounded-full"
                    style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }}
                  />
                  <span className="flex-1 truncate">{entry.name}</span>
                  <span className="text-muted-foreground">{entry.value}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
