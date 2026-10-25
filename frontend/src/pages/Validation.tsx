import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, AlertTriangle, ChevronLeft, ChevronRight, Info, Loader2 } from 'lucide-react'
import { useDocumentTypeCatalog, useValidationLog } from '@/lib/queries'
import { useTypeName } from '@/lib/labels'
import { humanizeFieldName } from '@/lib/extraction'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const ALL = '__all__'
const PAGE_SIZE = 25

const CATEGORY_OPTIONS = ['self', 'request_input', 'cross_document', 'conditional', 'reference_data', 'external_system']
const CATEGORY_LABEL: Record<string, string> = {
  self: 'Interna del documento',
  request_input: 'Datos de entrada',
  cross_document: 'Entre documentos',
  conditional: 'Condicional',
  reference_data: 'Datos de referencia',
  external_system: 'Sistema externo',
}

const SEVERITY_OPTIONS = ['error', 'warning', 'info']
const SEVERITY_LABEL: Record<string, string> = { error: 'Error', warning: 'Advertencia', info: 'Informativa' }
const SEVERITY_ICON = { error: AlertCircle, warning: AlertTriangle, info: Info }
const SEVERITY_CLASSES: Record<string, string> = {
  error: 'text-red-600 dark:text-red-400',
  warning: 'text-amber-600 dark:text-amber-400',
  info: 'text-muted-foreground',
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
}

export function ValidationPage() {
  const [category, setCategory] = useState(ALL)
  const [severity, setSeverity] = useState(ALL)
  const [documentType, setDocumentType] = useState(ALL)
  const [offset, setOffset] = useState(0)

  const { data: catalog } = useDocumentTypeCatalog()
  const typeName = useTypeName()
  const { data, isLoading, isFetching, isError } = useValidationLog({
    category: category === ALL ? undefined : category,
    severity: severity === ALL ? undefined : severity,
    document_type: documentType === ALL ? undefined : documentType,
    limit: PAGE_SIZE,
    offset,
  })

  function resetAndSet(setter: (value: string) => void) {
    return (value: string) => {
      setter(value)
      setOffset(0)
    }
  }

  const total = data?.total ?? 0
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Observaciones de validación</h1>
        <p className="text-muted-foreground">
          Lo que no se cumplió en cada documento{isError ? '' : ` (${total} en total)`}. Una comprobación que pasa no aparece aquí.
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Select value={category} onValueChange={resetAndSet(setCategory)}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Comprobación" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todas las comprobaciones</SelectItem>
            {CATEGORY_OPTIONS.map((c) => (
              <SelectItem key={c} value={c}>
                {CATEGORY_LABEL[c] ?? c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={severity} onValueChange={resetAndSet(setSeverity)}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Gravedad" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Toda gravedad</SelectItem>
            {SEVERITY_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>
                {SEVERITY_LABEL[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={documentType} onValueChange={resetAndSet(setDocumentType)}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Tipo de documento" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos los tipos</SelectItem>
            <SelectItem value="generic">Otro documento</SelectItem>
            {catalog?.registered.map((type) => (
              <SelectItem key={type.name} value={type.name}>
                {type.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : isError ? (
        <p className="text-sm text-destructive">No se pudieron cargar las observaciones. Vuelve a intentarlo en un momento.</p>
      ) : !data || data.issues.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin observaciones que coincidan con los filtros.</p>
      ) : (
        <>
          <Card>
            <CardContent className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Fecha</TableHead>
                    <TableHead>Documento</TableHead>
                    <TableHead>Observación</TableHead>
                    <TableHead>Dato</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.issues.map((issue) => {
                    const Icon = SEVERITY_ICON[issue.severity]
                    return (
                      <TableRow key={issue.id} className={isFetching ? 'opacity-60' : undefined}>
                        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatTimestamp(issue.created_at)}</TableCell>
                        <TableCell>
                          {issue.document_id ? (
                            <Link to={`/documents/${issue.document_id}`} className="text-xs text-primary hover:underline">
                              {issue.document_filename ?? 'Ver documento'}
                            </Link>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                          {issue.document_type && <div className="text-xs text-muted-foreground">{typeName(issue.document_type)}</div>}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-start gap-2">
                            <Icon className={`mt-0.5 size-4 shrink-0 ${SEVERITY_CLASSES[issue.severity]}`} aria-label={SEVERITY_LABEL[issue.severity]} />
                            <div className="flex flex-col gap-1">
                              <span className="whitespace-pre-line text-xs font-medium">{issue.message}</span>
                              <Badge variant="outline" className="w-fit text-[10px]">
                                {CATEGORY_LABEL[issue.category] ?? issue.category}
                              </Badge>
                              <details className="text-xs text-muted-foreground">
                                <summary className="cursor-pointer select-none">Detalle técnico</summary>
                                <div className="mt-1 flex flex-col gap-0.5">
                                  <code>{issue.rule_id}</code>
                                  <span>{issue.explanation}</span>
                                </div>
                              </details>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-xs">{issue.field_label ?? (issue.field_path ? humanizeFieldName(issue.field_path) : '—')}</TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Página {page} de {totalPages}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="icon" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                <ChevronLeft className="size-4" />
              </Button>
              <Button
                variant="outline"
                size="icon"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
