// The data catalog in words (VRT-34, VRT-89): each datum by its name, what
// it means and which documents bring it, grouped by what it describes; the
// same seen per document; the people of a case; the versions. The platform
// team edits by clicking: changes gather in a draft, saved in place and
// published from the bar at the bottom.
import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, FileText, Loader2, Pencil, Plus, Search, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DeleteButton } from '@/components/DeleteButton'
import { SharedConfigNote } from '@/components/layout/SharedConfigNote'
import { DatumDialog } from '@/components/semantic/DatumDialog'
import { NamedDialog } from '@/components/semantic/NamedDialog'
import { errorDetail } from '@/lib/apiErrors'
import { isPlatformAdmin } from '@/lib/auth'
import { COMPARISON, DATA_TYPE, PII, sourceLabel } from '@/lib/semanticCatalog'
import {
  useCatalogVersion,
  useCreateCatalogDraft,
  useDocumentTypeCatalog,
  useProcessProfiles,
  useProfileLibrary,
  usePublishCatalogVersion,
  useSemanticCatalog,
  useSemanticCatalogVersions,
} from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { SemanticAttribute, SemanticCatalog, SemanticEntity, SemanticRole } from '@/types/api'

const PREVIEW = 3

type Editing =
  | { kind: 'datum'; attribute: SemanticAttribute | null; entity: string }
  | { kind: 'entity'; item: SemanticEntity | null }
  | { kind: 'role'; item: SemanticRole | null }

interface Source {
  doc: string
  field: string
  role: string | null
}

function DatumCard({ attribute, sources, usedBy, onOpen }: { attribute: SemanticAttribute; sources: Source[]; usedBy: string[]; onOpen?: () => void }) {
  const [all, setAll] = useState(false)
  const docs = new Set(sources.map((s) => s.doc)).size
  const shown = all ? sources : sources.slice(0, PREVIEW)
  return (
    <Card className={cn('flex flex-col', onOpen && 'group cursor-pointer transition hover:border-primary/40 hover:shadow-sm')} onClick={onOpen}>
      <CardContent className="flex flex-1 flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-2">
          <span className="font-semibold group-hover:underline">{attribute.name}</span>
          {attribute.pii_class !== 'none' && (
            <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium', PII[attribute.pii_class].className)}>{PII[attribute.pii_class].label}</span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">{attribute.definition}</p>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span>{DATA_TYPE[attribute.data_type]}</span>
          <span>·</span>
          <span>
            Se compara: {COMPARISON[attribute.comparison].toLowerCase()}
            {attribute.tolerance ? ` (±${+(attribute.tolerance * 100).toFixed(2)}%)` : ''}
          </span>
          {attribute.format_cel && (
            <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400" title={attribute.format_cel}>
              <ShieldCheck className="size-3.5" /> Formato verificado
            </span>
          )}
        </div>
        <div className="mt-auto flex flex-col gap-1.5 border-t pt-3">
          {sources.length ? (
            <>
              <span className="text-xs font-medium text-muted-foreground">{docs === 1 ? 'Lo trae 1 documento' : `Lo traen ${docs} documentos`}</span>
              <ul className="flex flex-col gap-1 text-sm">
                {shown.map((s, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <FileText className="mt-0.5 size-3.5 shrink-0 text-primary" />
                    <span>
                      <span className="font-medium">{s.doc}</span>
                      <span className="text-muted-foreground">
                        {' '}
                        · {s.field}
                        {s.role && ` (${s.role})`}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
              {sources.length > PREVIEW && (
                <button
                  type="button"
                  className="self-start text-xs text-primary hover:underline"
                  onClick={(e) => {
                    e.stopPropagation()
                    setAll(!all)
                  }}
                >
                  {all ? 'Ver menos' : `y ${sources.length - PREVIEW} más`}
                </button>
              )}
            </>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle className="size-3.5" /> Ningún documento lo trae todavía
            </span>
          )}
          {usedBy.length > 0 && <span className="text-xs text-muted-foreground">Lo usan: {usedBy.join(', ')}</span>}
        </div>
      </CardContent>
    </Card>
  )
}

function NewCard({ label, onClick, className }: { label: string; onClick: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex min-h-32 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-sm text-muted-foreground transition hover:border-primary/40 hover:text-foreground',
        className,
      )}
    >
      <Plus className="size-5" />
      {label}
    </button>
  )
}

export function SemanticCatalogPage() {
  const admin = isPlatformAdmin()
  const { data: active, isLoading } = useSemanticCatalog()
  const { data: versions } = useSemanticCatalogVersions()
  const pendingDraft = versions?.find((v) => v.status === 'draft' && v.version > (active?.version ?? 0))
  const { data: pendingDetail } = useCatalogVersion(admin ? pendingDraft?.version : undefined)
  const { data: typeCatalog } = useDocumentTypeCatalog()
  const { data: library } = useProfileLibrary(undefined)
  const { data: profiles } = useProcessProfiles()
  const createDraft = useCreateCatalogDraft()
  const publish = usePublishCatalogVersion()
  const [edits, setEdits] = useState<SemanticCatalog | undefined>()
  const [editing, setEditing] = useState<Editing | null>(null)
  const [query, setQuery] = useState('')
  const [group, setGroup] = useState<string | null>(null)

  useEffect(() => {
    if (!edits) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [edits])

  // The platform team works on the pending draft; everyone else reads what is published.
  const base = admin && pendingDetail ? pendingDetail.catalog : active?.catalog
  const catalog = edits ?? base
  if (isLoading || !catalog || (admin && pendingDraft && !pendingDetail)) {
    return <Loader2 className="size-5 animate-spin text-muted-foreground" />
  }

  const types = typeCatalog?.registered ?? []
  const typeOf = (key: string) => types.find((t) => t.name === key)
  const roleName = (key: string) => catalog.roles.find((r) => r.key === key)?.name ?? key
  const attributeName = (key: string) => catalog.attributes.find((a) => a.key === key)?.name ?? key
  const processName = (key: string) => profiles?.find((p) => p.key === key)?.name ?? key
  const usedBy = (attribute: string) => (library?.attributes.find((a) => a.key === attribute)?.used_by ?? []).map(processName)
  const sourcesOf = (attribute: string): Source[] =>
    catalog.mappings
      .filter((m) => m.attribute === attribute)
      .map((m) => ({
        doc: typeOf(m.document_type)?.display_name ?? m.document_type,
        field: sourceLabel(typeOf(m.document_type), m.field_path),
        role: m.role === 'titular' ? null : roleName(m.role),
      }))
  const apply = (next: SemanticCatalog) => {
    setEdits(next)
    setEditing(null)
  }
  const open = (e: Editing) => admin && setEditing(e)

  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const matches = (a: SemanticAttribute) =>
    words.every((w) =>
      `${a.name} ${a.definition} ${a.key} ${sourcesOf(a.key)
        .map((s) => `${s.doc} ${s.field}`)
        .join(' ')}`
        .toLowerCase()
        .includes(w),
    )
  const orphans = catalog.attributes.filter((a) => !catalog.mappings.some((m) => m.attribute === a.key)).length
  const byType = types
    .map((t) => ({ type: t, mappings: catalog.mappings.filter((m) => m.document_type === t.name) }))
    .sort((a, b) => a.type.display_name.localeCompare(b.type.display_name))

  function save(then?: (version: number) => void) {
    createDraft.mutate(
      { catalog: edits!, draft: pendingDraft?.version },
      {
        onSuccess: (row) => {
          setEdits(undefined)
          if (then) then(row.version)
          else toast.success(`Borrador v${row.version} guardado. Publícalo cuando esté listo.`)
        },
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  function publishVersion(version: number) {
    publish.mutate(version, {
      onSuccess: () => toast.success(`Catálogo v${version} publicado. Cada proceso lo adopta al publicar su próxima versión.`),
      onError: (error) => toast.error(errorDetail(error)),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Catálogo de datos</h1>
          <p className="text-muted-foreground">
            El diccionario de Veritium: qué significa cada dato y de qué documentos sale. Con él compara un mismo dato entre documentos, y las reglas y
            procesos se escriben una sola vez para todos.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
          <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 text-emerald-700 dark:text-emerald-400">Publicado v{active?.version}</span>
          {admin && pendingDraft && <span className="rounded-full bg-amber-500/10 px-2.5 py-1 text-amber-700 dark:text-amber-400">Editando borrador v{pendingDraft.version}</span>}
        </div>
      </div>
      <SharedConfigNote show={!admin} />

      <Tabs defaultValue="data">
        <TabsList>
          <TabsTrigger value="data">Datos ({catalog.attributes.length})</TabsTrigger>
          <TabsTrigger value="documents">Por documento</TabsTrigger>
          <TabsTrigger value="roles">Personas del expediente ({catalog.roles.length})</TabsTrigger>
          <TabsTrigger value="versions">Versiones</TabsTrigger>
        </TabsList>

        <TabsContent value="data" className="mt-4 flex flex-col gap-8">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full max-w-sm">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Busca un dato o un documento, p. ej. «DNI»" className="pl-8" />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {[{ key: null, name: 'Todos', count: catalog.attributes.length }, ...catalog.entities.map((e) => ({ key: e.key, name: e.name, count: catalog.attributes.filter((a) => a.key.startsWith(`${e.key}.`)).length }))].map((g) => (
                <button
                  key={g.key ?? 'all'}
                  type="button"
                  onClick={() => setGroup(g.key)}
                  className={cn('rounded-full border px-3 py-1 text-sm transition', group === g.key ? 'border-primary bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:text-foreground')}
                >
                  {g.name} <span className="opacity-70">{g.count}</span>
                </button>
              ))}
            </div>
            {orphans > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-700 dark:text-amber-400">
                <AlertTriangle className="size-3.5" /> {orphans === 1 ? '1 dato sin documento' : `${orphans} datos sin documento`}
              </span>
            )}
          </div>

          {catalog.entities
            .filter((e) => !group || e.key === group)
            .map((entity) => {
              const data = catalog.attributes.filter((a) => a.key.startsWith(`${entity.key}.`) && matches(a))
              if (words.length && !data.length) return null
              return (
                <section key={entity.key} className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <h2 className="text-lg font-semibold">{entity.name}</h2>
                    <span className="text-sm text-muted-foreground">{data.length === 1 ? '1 dato' : `${data.length} datos`}</span>
                    {admin && (
                      <Button variant="ghost" size="icon" className="size-7 self-center text-muted-foreground" onClick={() => open({ kind: 'entity', item: entity })} aria-label={`Editar ${entity.name}`}>
                        <Pencil className="size-3.5" />
                      </Button>
                    )}
                    <p className="w-full text-sm text-muted-foreground">{entity.definition}</p>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
                    {data.map((a) => (
                      <DatumCard
                        key={a.key}
                        attribute={a}
                        sources={sourcesOf(a.key)}
                        usedBy={usedBy(a.key)}
                        onOpen={admin ? () => open({ kind: 'datum', attribute: a, entity: entity.key }) : undefined}
                      />
                    ))}
                    {admin && !words.length && <NewCard label={`Nuevo dato de ${entity.name}`} onClick={() => open({ kind: 'datum', attribute: null, entity: entity.key })} />}
                  </div>
                </section>
              )
            })}
          {words.length > 0 && !catalog.attributes.some(matches) && <p className="text-sm text-muted-foreground">Ningún dato coincide con «{query}».</p>}
          {admin && !group && !words.length && (
            <Button variant="outline" className="self-start" onClick={() => open({ kind: 'entity', item: null })}>
              <Plus className="size-4" /> Nuevo grupo de datos
            </Button>
          )}
        </TabsContent>

        <TabsContent value="documents" className="mt-4 flex flex-col gap-4">
          <p className="max-w-3xl text-sm text-muted-foreground">Qué datos del catálogo aporta cada tipo de documento, y de qué campo sale cada uno.</p>
          <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {byType
              .filter((t) => t.mappings.length)
              .map(({ type, mappings }) => (
                <Card key={type.name}>
                  <CardContent className="flex flex-col gap-3 p-5">
                    <div className="flex items-start gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <FileText className="size-4" />
                      </span>
                      <div className="flex flex-col">
                        <span className="font-semibold">{type.display_name}</span>
                        <span className="text-xs text-muted-foreground">{mappings.length === 1 ? 'Aporta 1 dato' : `Aporta ${mappings.length} datos`}</span>
                      </div>
                    </div>
                    <ul className="flex flex-col divide-y rounded-lg border text-sm">
                      {mappings.map((m, i) => {
                        const attribute = catalog.attributes.find((a) => a.key === m.attribute)
                        return (
                          <li key={i}>
                            <button
                              type="button"
                              disabled={!admin || !attribute}
                              onClick={() => attribute && open({ kind: 'datum', attribute, entity: attribute.key.split('.')[0] })}
                              className="flex w-full flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 text-left enabled:hover:bg-muted/50"
                            >
                              <span className="text-muted-foreground">{sourceLabel(type, m.field_path)}</span>
                              <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
                              <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">{attributeName(m.attribute)}</span>
                              {m.role !== 'titular' && <span className="text-xs text-muted-foreground">de {roleName(m.role).toLowerCase()}</span>}
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  </CardContent>
                </Card>
              ))}
          </div>
          {byType.some((t) => !t.mappings.length) && (
            <p className="text-sm text-muted-foreground">
              Aún sin datos en el catálogo:{' '}
              {byType
                .filter((t) => !t.mappings.length)
                .map((t) => t.type.display_name)
                .join(', ')}
              . Sus datos se leen igual, pero no se comparan con otros documentos.
            </p>
          )}
        </TabsContent>

        <TabsContent value="roles" className="mt-4 flex flex-col gap-4">
          <p className="max-w-3xl text-sm text-muted-foreground">
            De quién es cada dato en un expediente. Así Veritium no confunde el DNI del titular con el de su cónyuge o su aval.
          </p>
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {catalog.roles.map((r) => {
              const count = catalog.mappings.filter((m) => m.role === r.key).length
              return (
                <Card key={r.key} className={cn(admin && 'group cursor-pointer transition hover:border-primary/40 hover:shadow-sm')} onClick={() => open({ kind: 'role', item: r })}>
                  <CardContent className="flex flex-col gap-2 p-5">
                    <span className="font-semibold group-hover:underline">{r.name}</span>
                    <p className="text-sm text-muted-foreground">{r.definition}</p>
                    <span className="text-xs text-muted-foreground">{count === 0 ? 'Ningún documento trae datos suyos todavía' : count === 1 ? '1 dato de documentos es suyo' : `${count} datos de documentos son suyos`}</span>
                  </CardContent>
                </Card>
              )
            })}
            {admin && <NewCard label="Nueva persona del expediente" onClick={() => open({ kind: 'role', item: null })} />}
          </div>
        </TabsContent>

        <TabsContent value="versions" className="mt-4 flex flex-col gap-4">
          <p className="max-w-3xl text-sm text-muted-foreground">
            Cada proceso usa una versión del catálogo y adopta la nueva cuando se publica una versión del proceso. Así un cambio aquí nunca altera un
            expediente en curso.
          </p>
          <Card>
            <CardContent className="divide-y p-0">
              {(versions ?? []).map((v) => {
                const users = (profiles ?? []).filter((p) => p.versions.find((pv) => pv.version === p.active_version)?.semantic_catalog_version === v.version)
                return (
                  <div key={v.version} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-sm">
                    <span className="w-10 font-semibold">v{v.version}</span>
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 text-xs font-medium',
                        v.status === 'draft'
                          ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400'
                          : v.version === active?.version
                            ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                            : 'bg-muted text-muted-foreground',
                      )}
                    >
                      {v.status === 'draft' ? 'Borrador' : v.version === active?.version ? 'Vigente' : 'Anterior'}
                    </span>
                    <span className="text-muted-foreground">
                      {v.published_at ? `Publicada el ${new Date(v.published_at).toLocaleDateString()} por ${v.published_by}` : `Creada por ${v.created_by}`}
                    </span>
                    <span className="ml-auto text-xs text-muted-foreground">{users.length ? `La usan: ${users.map((p) => p.name).join(', ')}` : 'Ningún proceso la usa'}</span>
                  </div>
                )
              })}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {admin && (edits || pendingDraft) && (
        <div className="sticky bottom-4 z-20 mr-16 flex flex-wrap items-center gap-3 rounded-xl border bg-background/95 px-4 py-3 shadow-lg backdrop-blur">
          <span className="text-sm">
            {edits ? (
              <span className="font-medium">Tienes cambios sin guardar.</span>
            ) : (
              <>
                <span className="font-medium">Borrador v{pendingDraft!.version} sin publicar.</span>{' '}
                <span className="text-muted-foreground">Los procesos siguen usando la v{active?.version}.</span>
              </>
            )}
          </span>
          <div className="ml-auto flex flex-wrap gap-2">
            {edits ? (
              <>
                <Button variant="ghost" onClick={() => setEdits(undefined)} disabled={createDraft.isPending}>
                  Descartar cambios
                </Button>
                <Button variant="outline" onClick={() => save()} disabled={createDraft.isPending}>
                  {createDraft.isPending && <Loader2 className="size-4 animate-spin" />} Guardar borrador
                </Button>
                <Button onClick={() => save(publishVersion)} disabled={createDraft.isPending || publish.isPending}>
                  Publicar
                </Button>
              </>
            ) : (
              <>
                <DeleteButton
                  label="Descartar borrador"
                  path={`/v1/semantic-catalog/versions/${pendingDraft!.version}`}
                  question={`Se eliminará para siempre el borrador v${pendingDraft!.version} del catálogo. Lo publicado no cambia.`}
                />
                <Button onClick={() => publishVersion(pendingDraft!.version)} disabled={publish.isPending}>
                  {publish.isPending && <Loader2 className="size-4 animate-spin" />} Publicar v{pendingDraft!.version}
                </Button>
              </>
            )}
          </div>
        </div>
      )}

      {editing?.kind === 'datum' && (
        <DatumDialog
          catalog={catalog}
          attribute={editing.attribute}
          entity={editing.entity}
          types={types}
          usedBy={editing.attribute ? usedBy(editing.attribute.key) : []}
          onApply={apply}
          onClose={() => setEditing(null)}
        />
      )}
      {editing?.kind === 'entity' && (
        <NamedDialog
          title={editing.item ? editing.item.name : 'Nuevo grupo de datos'}
          hint="Un grupo reúne los datos de una misma cosa: una persona, su empleador, su ingreso, el crédito."
          item={editing.item}
          taken={catalog.entities.map((e) => e.key)}
          inUse={(() => {
            const n = editing.item ? catalog.attributes.filter((a) => a.key.startsWith(`${editing.item!.key}.`)).length : 0
            return n ? `Tiene ${n} datos: quítalos antes de quitar el grupo.` : null
          })()}
          onApply={(e) => apply({ ...catalog, entities: editing.item ? catalog.entities.map((x) => (x.key === e.key ? e : x)) : [...catalog.entities, e] })}
          onRemove={() => apply({ ...catalog, entities: catalog.entities.filter((x) => x.key !== editing.item!.key) })}
          onClose={() => setEditing(null)}
        />
      )}
      {editing?.kind === 'role' && (
        <NamedDialog
          title={editing.item ? editing.item.name : 'Nueva persona del expediente'}
          hint="Quién es, en el expediente, la persona a la que pertenece un dato: titular, cónyuge, aval…"
          item={editing.item}
          taken={catalog.roles.map((r) => r.key)}
          inUse={(() => {
            const n = editing.item ? catalog.mappings.filter((m) => m.role === editing.item!.key).length : 0
            return n ? `${n} datos de documentos son suyos: cámbialos antes de quitarla.` : null
          })()}
          onApply={(r) => apply({ ...catalog, roles: editing.item ? catalog.roles.map((x) => (x.key === r.key ? r : x)) : [...catalog.roles, r] })}
          onRemove={() => apply({ ...catalog, roles: catalog.roles.filter((x) => x.key !== editing.item!.key) })}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
