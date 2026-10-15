import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuditLog, useCorrectionSummary, useDataAccessLog, useDocumentTypeCatalog } from '@/lib/queries'
import { isAdmin } from '@/lib/auth'
import { humanizeFieldName, formatValue } from '@/lib/extraction'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
}

const CHANNEL_LABEL: Record<string, string> = { web: 'Pantalla', api: 'Sistema conectado' }

/** Who saw the unit's personal data, or removed it (VRT-58). Admins only. */
function DataAccessLog() {
  const { data: entries, isLoading } = useDataAccessLog()
  return (
    <Card>
      <CardHeader>
        <CardTitle>Accesos a datos personales</CardTitle>
        <CardDescription>
          Cada vez que alguien pidió ver los datos personales de un expediente, descargó un original o buscó por un dato. El registro nunca guarda los
          datos.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        {isLoading ? (
          <Loader2 className="m-4 size-5 animate-spin text-muted-foreground" />
        ) : !entries?.length ? (
          <p className="p-4 text-sm text-muted-foreground">Todavía nadie pidió ver datos personales.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Cuándo</TableHead>
                <TableHead>Quién</TableHead>
                <TableHead>Qué hizo</TableHead>
                <TableHead>Expediente</TableHead>
                <TableHead>Para qué</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="whitespace-nowrap text-xs">{formatTimestamp(e.at)}</TableCell>
                  <TableCell className="text-xs">
                    <div>{e.actor}</div>
                    <div className="text-muted-foreground">
                      {e.role} · {CHANNEL_LABEL[e.channel] ?? e.channel}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">
                    {e.action_label} <span className="text-muted-foreground">({e.what})</span>
                  </TableCell>
                  <TableCell className="text-xs">
                    {e.case_id ? <Link to={`/cases/${e.case_id}`} className="underline-offset-2 hover:underline">{e.case_ref ?? e.case_id.slice(0, 8)}</Link> : '—'}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{e.reason ?? '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function CorrectionSummary() {
  const { data: rows } = useCorrectionSummary()
  const { data: types } = useDocumentTypeCatalog()
  if (!rows || rows.length === 0) return null
  const typeName = Object.fromEntries((types?.registered ?? []).map((t) => [t.name, t.display_name]))
  const byReason = new Map<string, { label: string; total: number; types: string[] }>()
  for (const r of rows) {
    const key = r.reason_code ?? '—'
    const entry = byReason.get(key) ?? { label: r.reason_label, total: 0, types: [] }
    entry.total += r.count
    entry.types.push(`${r.document_type ? (typeName[r.document_type] ?? r.document_type) : 'sin tipo'} (${r.count})`)
    byReason.set(key, entry)
  }
  const total = rows.reduce((n, r) => n + r.count, 0)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Por qué se corrige</CardTitle>
        <CardDescription>{total} correcciones, por motivo y tipo de documento.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        {[...byReason.values()]
          .sort((a, b) => b.total - a.total)
          .map((r) => (
            <div key={r.label} className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{r.total}</Badge>
              <span className="font-medium">{r.label}</span>
              <span className="text-xs text-muted-foreground">{r.types.join(' · ')}</span>
            </div>
          ))}
      </CardContent>
    </Card>
  )
}

export function AuditPage() {
  const { data, isLoading } = useAuditLog({ limit: 100 })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Auditoría</h1>
        <p className="text-muted-foreground">Historial completo de correcciones hechas desde la cola de revisión, con su motivo y sustento.</p>
      </div>

      <CorrectionSummary />

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : !data || data.entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">Aún no se ha corregido ningún campo.</p>
      ) : (
        <Card>
          <CardContent className="overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Documento</TableHead>
                  <TableHead>Campo</TableHead>
                  <TableHead>Valor original</TableHead>
                  <TableHead>Valor corregido</TableHead>
                  <TableHead>Motivo</TableHead>
                  <TableHead>Revisor</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.entries.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatTimestamp(entry.timestamp)}
                    </TableCell>
                    <TableCell>
                      <Link to={`/documents/${entry.document_id}`} className="text-primary hover:underline">
                        Ver documento
                      </Link>
                    </TableCell>
                    <TableCell className="text-xs">{humanizeFieldName(entry.field_path)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground line-through decoration-red-400">
                      {formatValue(entry.original_value.value)}
                    </TableCell>
                    <TableCell className="text-xs font-medium">{formatValue(entry.corrected_value.value)}</TableCell>
                    <TableCell className="text-xs">
                      {entry.reason_label ?? <span className="text-muted-foreground">—</span>}
                      {entry.justification && <div className="text-muted-foreground">{entry.justification}</div>}
                    </TableCell>
                    <TableCell className="text-xs">{entry.reviewer_identity}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      {isAdmin() && <DataAccessLog />}
    </div>
  )
}
