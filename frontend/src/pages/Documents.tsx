// The dedicated document browser — the dashboard's "recent documents" list
// caps at a handful of rows and has no filter controls; this page is the
// real way to work the full corpus by status, type, process or
// needs_review, and to search it (VRT-59): by a DNI or a name even misread,
// or by what a document is about. Each result says where it matched —
// never what it says.
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight, FileText, Loader2, Search } from 'lucide-react'
import { useDocumentList, useDocumentTypeCatalog, useProcessProfiles } from '@/lib/queries'
import type { SearchMatch } from '@/types/api'
import { DeleteButton } from '@/components/DeleteButton'
import { isAdmin } from '@/lib/auth'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const SEARCH_DEBOUNCE_MS = 400

const STATUS_OPTIONS = [
  'uploaded',
  'parsing',
  'classifying',
  'extracting',
  'segmented',
  'extracted',
  'validating',
  'needs_review',
  'completed',
  'failed',
]
const ALL = '__all__'
const PAGE_SIZE = 25

function matchLabel(match: SearchMatch): string {
  if (match.where === 'valores') return 'En los datos extraídos'
  if (match.where === 'archivo') return 'En el nombre del archivo'
  return match.page ? `En el texto, página ${match.page}` : 'En el texto'
}

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  completed: 'secondary',
  needs_review: 'destructive',
  failed: 'destructive',
}

export function DocumentsPage() {
  const [status, setStatus] = useState(ALL)
  const [documentType, setDocumentType] = useState(ALL)
  const [needsReview, setNeedsReview] = useState(ALL)
  const [profile, setProfile] = useState(ALL)
  const [searchInput, setSearchInput] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)

  // Debounced separately from the other filters (which apply immediately on
  // select) since this fires on every keystroke — waits for a pause before
  // hitting the API instead of a request per character.
  useEffect(() => {
    const timeout = setTimeout(() => {
      setQ(searchInput.trim())
      setOffset(0)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timeout)
  }, [searchInput])

  const { data: catalog } = useDocumentTypeCatalog()
  const { data: profiles } = useProcessProfiles()
  const { data, isLoading, isFetching } = useDocumentList({
    status: status === ALL ? undefined : status,
    document_type: documentType === ALL ? undefined : documentType,
    needs_review: needsReview === ALL ? undefined : needsReview === 'true',
    profile: profile === ALL ? undefined : profile,
    q: q || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const documents = useMemo(() => (data?.documents ?? []).filter((doc) => doc.status !== 'segmented'), [data])

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
        <h1 className="text-2xl font-semibold tracking-tight">Documentos</h1>
        <p className="text-muted-foreground">Explora y filtra todos los documentos procesados ({total} en total).</p>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative w-96">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar por DNI, nombre o de qué trata el documento..."
            className="pl-8"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>

        <Select value={status} onValueChange={resetAndSet(setStatus)}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Estado" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos los estados</SelectItem>
            {STATUS_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
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
            <SelectItem value="generic">generic</SelectItem>
            {catalog?.registered.map((type) => (
              <SelectItem key={type.name} value={type.name}>
                {type.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={profile} onValueChange={resetAndSet(setProfile)}>
          <SelectTrigger className="w-52">
            <SelectValue placeholder="Proceso" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos los procesos</SelectItem>
            {profiles?.map((p) => (
              <SelectItem key={p.key} value={p.key}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={needsReview} onValueChange={resetAndSet(setNeedsReview)}>
          <SelectTrigger className="w-52">
            <SelectValue placeholder="Revisión" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos</SelectItem>
            <SelectItem value="true">Requieren revisión</SelectItem>
            <SelectItem value="false">No requieren revisión</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Documento</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Confianza</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Revisión</TableHead>
                  {isAdmin() && <TableHead className="w-10" />}
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-sm text-muted-foreground">
                      Sin documentos que coincidan con los filtros.
                    </TableCell>
                  </TableRow>
                ) : (
                  documents.map((doc) => (
                    <TableRow key={doc.id} className={isFetching ? 'opacity-60' : undefined}>
                      <TableCell>
                        <Link to={`/documents/${doc.id}`} className="flex items-center gap-2 hover:underline">
                          <FileText className="size-4 shrink-0 text-muted-foreground" />
                          <span className="truncate">{doc.original_filename}</span>
                        </Link>
                        {doc.match && <span className="mt-0.5 block pl-6 text-xs text-muted-foreground">{matchLabel(doc.match)}</span>}
                      </TableCell>
                      <TableCell>
                        {doc.document_type ? (
                          <Badge variant="outline" className="text-[10px]">
                            {doc.document_type}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {doc.classification_confidence !== null ? (
                          <span className="text-xs">{(doc.classification_confidence * 100).toFixed(0)}%</span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={STATUS_VARIANT[doc.status] ?? 'secondary'} className="text-[10px]">
                          {doc.status}
                        </Badge>
                      </TableCell>
                      <TableCell>{doc.needs_review && <Badge variant="destructive">Requiere revisión</Badge>}</TableCell>
                      {isAdmin() && (
                        <TableCell>
                          <DeleteButton
                            iconOnly
                            label="Eliminar documento"
                            path={`/documents/${doc.id}`}
                            question="Se eliminará para siempre este documento con su archivo y lo leído de él, y su expediente se volverá a evaluar sin él."
                          />
                        </TableCell>
                      )}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

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
