// The dedicated document browser — the dashboard's "recent documents" list
// caps at a handful of rows and has no filter controls; this page is the
// real way to work the full corpus by status, type, process or
// needs_review, and to search it (VRT-59): by a DNI or a name even misread,
// or by what a document is about. Each result says where it matched —
// never what it says.
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, FileText, Loader2, Search } from 'lucide-react'
import { useDocumentList, useDocumentTypeCatalog, useProcessProfiles } from '@/lib/queries'
import type { SearchMatch } from '@/types/api'
import { DeleteButton } from '@/components/DeleteButton'
import { StatusBadge } from '@/components/StatusBadge'
import { documentStatus, useTypeName } from '@/lib/labels'
import { isAdmin } from '@/lib/auth'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const SEARCH_DEBOUNCE_MS = 400

// The states a person filters by; the ones in between last seconds.
const STATUS_OPTIONS = ['needs_review', 'completed', 'failed']
const ALL = '__all__'
const PAGE_SIZE = 25

function matchLabel(match: SearchMatch): string {
  if (match.where === 'valores') return 'En los datos extraídos'
  if (match.where === 'archivo') return 'En el nombre del archivo'
  return match.page ? `En el texto, página ${match.page}` : 'En el texto'
}

export function DocumentsPage() {
  const [status, setStatus] = useState(ALL)
  const [documentType, setDocumentType] = useState(ALL)
  const [profile, setProfile] = useState(ALL)
  const [params] = useSearchParams()
  const [searchInput, setSearchInput] = useState(params.get('q') ?? '')
  const [q, setQ] = useState(params.get('q') ?? '')

  // A search from the top bar arrives in the URL (VRT-73).
  const fromBar = params.get('q')
  const [seenFromBar, setSeenFromBar] = useState(fromBar)
  if (fromBar !== seenFromBar) {
    setSeenFromBar(fromBar)
    if (fromBar !== null) setSearchInput(fromBar)
  }
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
  const typeName = useTypeName()
  const { data: profiles } = useProcessProfiles()
  const { data, isLoading, isFetching } = useDocumentList({
    status: status === ALL ? undefined : status,
    document_type: documentType === ALL ? undefined : documentType,
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
        <p className="text-muted-foreground">Todos los documentos recibidos ({total}). Busca por DNI, nombre o de qué trata, o filtra por estado, tipo y proceso.</p>
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
                {documentStatus(s).label}
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
                  <TableHead>Expediente</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Llegó</TableHead>
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
                        <span className="text-sm">{typeName(doc.document_type)}</span>
                      </TableCell>
                      <TableCell>
                        <Link to={`/cases/${doc.batch_id}`} className="text-sm hover:underline">
                          {doc.case_ref ?? doc.batch_id.slice(0, 8)}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={doc.needs_review ? 'needs_review' : doc.status} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                        {doc.created_at ? new Date(doc.created_at).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'}
                      </TableCell>
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
