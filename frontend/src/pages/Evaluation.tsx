// Evaluation suites (VRT-42): documents whose right answer is known, run
// against the current models, prompts and document types. A suite comes
// from a CSV/Excel table plus its files, or from the human corrections.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute } from '@/lib/auth'
import { percent } from '@/lib/evaluation'
import { downloadFile, useCreateEvalSuite, useCreateGoldenSet, useDocumentTypeCatalog, useEvalSuites } from '@/lib/queries'

function FromTable() {
  const create = useCreateEvalSuite()
  const { data: types } = useDocumentTypeCatalog()
  const [name, setName] = useState('')
  const [table, setTable] = useState<File | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [templateType, setTemplateType] = useState('')

  return (
    <Card>
      <CardHeader>
        <CardTitle>Desde una tabla</CardTitle>
        <CardDescription>
          CSV o Excel con las columnas <code>archivo</code>, <code>tipo</code>, <code>paginas</code> (opcional, p. ej. 1-2) y una columna por campo con el
          valor esperado. Una celda vacía no se evalúa. Sube también los documentos que nombra la tabla.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={templateType} onValueChange={setTemplateType}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="Plantilla de columnas para…" />
            </SelectTrigger>
            <SelectContent>
              {(types?.registered ?? []).map((t) => (
                <SelectItem key={t.name} value={t.name}>
                  {t.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            disabled={!templateType}
            onClick={() => downloadFile('/v1/eval-suites/template', { document_type: templateType }, 'evaluacion.csv').catch((e) => toast.error(errorDetail(e)))}
          >
            <Download className="size-3.5" /> Descargar plantilla
          </Button>
        </div>
        <Input placeholder="Nombre de la suite" value={name} onChange={(e) => setName(e.target.value)} className="max-w-md" />
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Tabla (.csv o .xlsx)</span>
          <Input type="file" accept=".csv,.xlsx" onChange={(e) => setTable(e.target.files?.[0] ?? null)} className="max-w-md" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Documentos</span>
          <Input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} className="max-w-md" />
        </label>
        <div>
          <Button
            disabled={name.trim().length < 3 || !table || files.length === 0 || create.isPending}
            onClick={() =>
              table &&
              create.mutate(
                { name: name.trim(), description: '', table, files },
                { onSuccess: (s) => toast.success(`Suite creada con ${s.case_count} casos.`), onError: (e) => toast.error(errorDetail(e)) },
              )
            }
          >
            {create.isPending && <Loader2 className="size-4 animate-spin" />} Crear suite
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function FromCorrections() {
  const create = useCreateGoldenSet()
  const [name, setName] = useState('')
  return (
    <Card>
      <CardHeader>
        <CardTitle>Golden set desde las correcciones</CardTitle>
        <CardDescription>
          Cada documento que un revisor corrigió, con el tipo y los valores que dejó. Mide justo donde el modelo se equivocó antes.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-2">
        <Input placeholder="Nombre del golden set" value={name} onChange={(e) => setName(e.target.value)} className="max-w-md" />
        <Button
          disabled={name.trim().length < 3 || create.isPending}
          onClick={() =>
            create.mutate(
              { name: name.trim() },
              { onSuccess: (s) => toast.success(`Golden set con ${s.case_count} documentos.`), onError: (e) => toast.error(errorDetail(e)) },
            )
          }
        >
          {create.isPending && <Loader2 className="size-4 animate-spin" />} Crear golden set
        </Button>
      </CardContent>
    </Card>
  )
}

export function EvaluationPage() {
  const { data: suites, isLoading } = useEvalSuites()

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Evaluación</h1>
        <p className="text-muted-foreground">
          Suites de documentos con su respuesta correcta. Correrlas mide los modelos, prompts y tipos documentales actuales, y compara cada corrida con la
          anterior antes de publicar un cambio.
        </p>
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Suite</TableHead>
              <TableHead>Origen</TableHead>
              <TableHead>Casos</TableHead>
              <TableHead>Última corrida</TableHead>
              <TableHead>Clasificación</TableHead>
              <TableHead>Campos</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(suites ?? []).length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-sm text-muted-foreground">
                  Todavía no hay suites.
                </TableCell>
              </TableRow>
            )}
            {(suites ?? []).map((s) => (
              <TableRow key={s.id}>
                <TableCell>
                  <Link to={`/evaluation/${s.id}`} className="font-medium underline-offset-4 hover:underline">
                    {s.name}
                  </Link>
                  {s.description && <div className="text-xs text-muted-foreground">{s.description}</div>}
                </TableCell>
                <TableCell>
                  <Badge variant="outline">{s.source === 'corrections' ? 'correcciones' : 'tabla'}</Badge>
                </TableCell>
                <TableCell>{s.case_count}</TableCell>
                <TableCell className="text-sm">{s.latest_run ? `${s.latest_run.status} · ${new Date(s.latest_run.created_at).toLocaleString()}` : '—'}</TableCell>
                <TableCell>{percent(s.latest_run?.metrics?.classification)}</TableCell>
                <TableCell>{percent(s.latest_run?.metrics?.fields)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {canExecute() && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <FromTable />
          <FromCorrections />
        </div>
      )}
    </div>
  )
}
