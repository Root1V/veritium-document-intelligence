// The dedicated document browser — the dashboard's "recent documents" list
// caps at a handful of rows and has no filter controls; this page is the
// real way to work the full corpus by status, type, process or
// needs_review, and to search it (VRT-59): by a DNI or a name even misread,
// or by what a document is about. Each result says where it matched —
// never what it says. The state is a row of buttons and each document one
// line; it is deleted from inside it (VRT-109).
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, FileText, Loader2, Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDocumentList, useDocumentTypeCatalog, useProcessProfiles } from '@/lib/queries'
import type { SearchMatch } from '@/types/api'
import { StatusBadge } from '@/components/StatusBadge'
import { documentStatus, useTypeName } from '@/lib/labels'
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
        <p className="text-muted-foreground">Todos los documentos recibidos. Busca por DNI, nombre o de qué trata, o filtra por estado, tipo y proceso.</p>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Estado">
        {[ALL, ...STATUS_OPTIONS].map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={status === key}
            onClick={() => resetAndSet(setStatus)(key)}
            className={cn('rounded-full border px-3 py-1 text-xs font-medium transition', status === key ? 'border-primary bg-primary text-primary-foreground' : 'bg-card hover:border-primary/40')}
          >
            {key === ALL ? 'Todos' : documentStatus(key).label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative w-full sm:w-96">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar por DNI, nombre o de qué trata el documento..."
            className="pl-8"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>

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
          {documents.length === 0 ? (
            <p className="text-sm text-muted-foreground">Ningún documento coincide con los filtros.</p>
          ) : (
            <div className={cn('flex flex-col overflow-hidden rounded-xl border bg-card', isFetching && 'opacity-60')}>
              {documents.map((doc) => (
                <div key={doc.id} className="flex items-center gap-3 border-b px-4 py-2.5 last:border-0 hover:bg-muted/50">
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <Link to={`/documents/${doc.id}`} className="truncate font-medium hover:underline">
                      {doc.original_filename}
                    </Link>
                    <span className="flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
                      {typeName(doc.document_type)} ·
                      <Link to={`/cases/${doc.batch_id}`} className="text-primary hover:underline">
                        {doc.case_ref ?? `Expediente ${doc.batch_id.slice(0, 8)}`}
                      </Link>
                      {doc.match && <span>· {matchLabel(doc.match)}</span>}
                    </span>
                  </span>
                  <StatusBadge status={doc.needs_review ? 'needs_review' : doc.status} />
                  <span className="hidden w-24 shrink-0 text-right text-xs text-muted-foreground sm:block">
                    {doc.created_at ? new Date(doc.created_at).toLocaleDateString('es-PE', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'}
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {total} documentos · página {page} de {totalPages}
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
