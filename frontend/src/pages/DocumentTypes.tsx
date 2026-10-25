// The documents Veritium recognizes (VRT-32, VRT-88): each as a card that
// says what it is, how many data it reads and which processes ask for it;
// the full list of its data opens on click. Types found in cases and not
// registered yet come first, since they wait for someone.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Loader2, MoreHorizontal, Plus, Search, Sparkles, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { DeleteButton, useDeleteAction } from '@/components/DeleteButton'
import { TypeDetail } from '@/components/documentTypes/TypeDetail'
import { SharedConfigNote } from '@/components/layout/SharedConfigNote'
import { canExecute, isPlatformAdmin } from '@/lib/auth'
import { fieldName, flatten, meaningOf } from '@/lib/documentTypes'
import { useDocumentTypeCatalog, useProcessProfiles, useProfileLibrary, useSemanticCatalog } from '@/lib/queries'
import type { DocumentTypeInfo, SemanticCatalog } from '@/types/api'

const PREVIEW = 6

function TypeCard({ type, catalog, usedBy, onOpen }: { type: DocumentTypeInfo; catalog: SemanticCatalog | undefined; usedBy: string[]; onOpen: () => void }) {
  const rows = flatten(type.fields)
  const meaningful = rows.filter((r) => meaningOf(catalog, type.name, r.path)).length
  const remove = useDeleteAction({
    path: `/v1/document-types/${type.name}`,
    question: `¿Eliminar el tipo «${type.display_name}»? Si nada lo usó, se borra del todo; si ya hay documentos, procesos o mapeos que lo usan, se archiva: ningún documento nuevo se clasificará así y lo ya leído se conserva.`,
  })

  return (
    <Card className="group flex cursor-pointer flex-col transition hover:border-primary/40 hover:shadow-sm" onClick={onOpen}>
      <CardContent className="flex flex-1 flex-col gap-3 p-5">
        <div className="flex items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileText className="size-4" />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="font-semibold group-hover:underline">{type.display_name}</span>
            <p className="line-clamp-2 text-sm text-muted-foreground first-letter:uppercase">{type.description}</p>
          </div>
          {isPlatformAdmin() && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                <Button variant="ghost" size="icon" className="size-8 shrink-0" aria-label="Más acciones">
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                <DropdownMenuItem variant="destructive" disabled={remove.pending} onSelect={remove.run}>
                  <Trash2 className="size-4" /> Eliminar tipo
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {type.fields.slice(0, PREVIEW).map((f) => (
            <span key={f.name} className="rounded-md border px-2 py-0.5 text-xs text-muted-foreground">
              {fieldName(f)}
            </span>
          ))}
          {type.fields.length > PREVIEW && <span className="px-1 py-0.5 text-xs text-muted-foreground">y {type.fields.length - PREVIEW} más</span>}
        </div>

        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
          <span>
            {rows.length} datos · {meaningful} con significado
          </span>
          <span className="truncate">{usedBy.length ? `Lo piden: ${usedBy.join(', ')}` : 'Ningún proceso lo pide'}</span>
        </div>
      </CardContent>
    </Card>
  )
}

export function DocumentTypesPage() {
  const { data: types, isLoading } = useDocumentTypeCatalog()
  const { data: semantic } = useSemanticCatalog()
  const { data: library } = useProfileLibrary(undefined)
  const { data: profiles } = useProcessProfiles()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const catalog = semantic?.catalog
  const processName = (key: string) => profiles?.find((p) => p.key === key)?.name ?? key
  // Asked for by type, or accepted for a datum it brings (an income proof any payslip satisfies).
  const usedBy = (key: string) => {
    const byType = library?.document_types.find((t) => t.key === key)?.used_by ?? []
    const byData = (library?.attributes ?? []).filter((a) => a.providers.some((p) => p.document_type === key)).flatMap((a) => a.used_by)
    return [...new Set([...byType, ...byData])].map(processName)
  }
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = (types?.registered ?? [])
    .filter((t) => words.every((w) => `${t.display_name} ${t.description} ${flatten(t.fields).map((r) => fieldName(r.field)).join(' ')}`.toLowerCase().includes(w)))
    .sort((a, b) => a.display_name.localeCompare(b.display_name))
  const opened = types?.registered.find((t) => t.name === open)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Tipos de documento</h1>
          <p className="text-muted-foreground">
            Los documentos que Veritium reconoce y los datos que lee de cada uno. Para uno nuevo basta un documento de ejemplo: Veritium propone sus datos y
            tú los revisas.
          </p>
        </div>
        {isPlatformAdmin() && (
          <Button asChild>
            <Link to="/document-types/new">
              <Plus className="size-4" /> Nuevo tipo
            </Link>
          </Button>
        )}
      </div>
      <SharedConfigNote show={!isPlatformAdmin()} />

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : !types ? (
        <p className="text-sm text-muted-foreground">No se pudo cargar el catálogo.</p>
      ) : (
        <>
          {types.pending.length > 0 && (
            <section className="flex flex-col gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
              <div className="flex items-center gap-2">
                <Sparkles className="size-4 text-amber-600 dark:text-amber-400" />
                <h2 className="text-sm font-semibold">Detectados en expedientes, por registrar ({types.pending.length})</h2>
              </div>
              <p className="-mt-1 text-xs text-muted-foreground">
                Llegaron documentos que no son de ningún tipo conocido y alguien aceptó registrarlos. Regístralos para que Veritium los reconozca.
              </p>
              <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
                {types.pending.map((t) => (
                  <div key={t.suggestion_id} className="flex flex-col gap-2 rounded-lg border bg-card p-3">
                    <span className="font-medium">{t.suggested_display_name}</span>
                    <p className="line-clamp-2 text-xs text-muted-foreground">{t.rationale}</p>
                    <div className="mt-auto flex flex-wrap items-center gap-2">
                      {isPlatformAdmin() && (
                        <Button asChild size="sm">
                          <Link
                            to={`/document-types/new?document_id=${t.document_id}&suggestion_id=${t.suggestion_id}&name=${encodeURIComponent(t.suggested_display_name)}`}
                          >
                            Registrar
                          </Link>
                        </Button>
                      )}
                      {canExecute() && (
                        <DeleteButton
                          label="Descartar"
                          path={`/type-suggestions/${t.suggestion_id}`}
                          question="Se eliminará para siempre esta sugerencia. El documento que la originó no cambia."
                        />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full max-w-md">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Busca por documento o por dato, p. ej. «DNI»" className="pl-8" />
            </div>
            <span className="text-sm text-muted-foreground">
              {shown.length === types.registered.length ? `${types.registered.length} tipos` : `${shown.length} de ${types.registered.length} tipos`}
            </span>
          </div>

          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {shown.map((t) => (
              <TypeCard key={t.name} type={t} catalog={catalog} usedBy={usedBy(t.name)} onOpen={() => setOpen(t.name)} />
            ))}
            {isPlatformAdmin() && !query && (
              <Link
                to="/document-types/new"
                className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
              >
                <Plus className="size-6" />
                <span className="font-medium">Nuevo tipo de documento</span>
                <span className="text-sm">Desde un documento de ejemplo.</span>
              </Link>
            )}
          </div>
          {shown.length === 0 && <p className="text-sm text-muted-foreground">Ningún tipo coincide con «{query}».</p>}
        </>
      )}

      {opened && <TypeDetail type={opened} catalog={catalog} usedBy={usedBy(opened.name)} onClose={() => setOpen(null)} />}
    </div>
  )
}
