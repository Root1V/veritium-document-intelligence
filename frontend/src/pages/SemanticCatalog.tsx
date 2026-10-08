import { useMemo, useState, type ReactNode } from 'react'
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { errorDetail } from '@/lib/apiErrors'
import { isAdmin } from '@/lib/auth'
import {
  useCreateCatalogDraft,
  useDocumentTypeCatalog,
  useProcessProfiles,
  usePublishCatalogVersion,
  useSemanticCatalog,
  useSemanticCatalogVersions,
} from '@/lib/queries'
import type { DocumentTypeFieldInfo, FieldMapping, SemanticAttribute, SemanticCatalog } from '@/types/api'

// --- a small editable table: read mode shows text, edit mode the editors ---

interface Column<T> {
  label: string
  read: (row: T) => ReactNode
  edit: (row: T, set: (row: T) => void) => ReactNode
}

function EditableTable<T>({
  rows,
  columns,
  editing,
  onChange,
  blank,
}: {
  rows: T[]
  columns: Column<T>[]
  editing: boolean
  onChange: (rows: T[]) => void
  blank: () => T
}) {
  return (
    <div className="flex flex-col gap-2">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((c) => (
              <TableHead key={c.label}>{c.label}</TableHead>
            ))}
            {editing && <TableHead className="w-10" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={i}>
              {columns.map((c) => (
                <TableCell key={c.label} className="align-top text-sm">
                  {editing ? c.edit(row, (next) => onChange(rows.map((r, j) => (j === i ? next : r)))) : c.read(row)}
                </TableCell>
              ))}
              {editing && (
                <TableCell className="align-top">
                  <Button variant="ghost" size="icon" onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label="Quitar">
                    <Trash2 className="size-4" />
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {editing && (
        <Button variant="outline" size="sm" className="self-start" onClick={() => onChange([...rows, blank()])}>
          <Plus className="size-3.5" /> Agregar
        </Button>
      )}
    </div>
  )
}

function text<T>(get: (row: T) => string, set: (row: T, value: string) => T, mono = false): Column<T>['edit'] {
  return (row, onSet) => <Input value={get(row)} onChange={(e) => onSet(set(row, e.target.value))} className={mono ? 'font-mono text-xs' : 'text-xs'} />
}

function choice<T>(options: readonly string[], get: (row: T) => string, set: (row: T, value: string) => T): Column<T>['edit'] {
  return (row, onSet) => (
    <Select value={get(row)} onValueChange={(v) => onSet(set(row, v))}>
      <SelectTrigger className="h-8 text-xs">
        <SelectValue placeholder="—" />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o} value={o}>
            {o}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function fieldPaths(fields: DocumentTypeFieldInfo[]): string[] {
  return fields.flatMap((f) => (f.items ? f.items.map((i) => `${f.name}[0].${i.name}`) : [f.name]))
}

const joinPath = (p: string | string[]) => (Array.isArray(p) ? p.join(' + ') : p)
const splitPath = (v: string): string | string[] => {
  const parts = v.split('+').map((s) => s.trim()).filter(Boolean)
  return parts.length > 1 ? parts : (parts[0] ?? '')
}

export function SemanticCatalogPage() {
  const { data: active, isLoading } = useSemanticCatalog()
  const { data: versions } = useSemanticCatalogVersions()
  const { data: types } = useDocumentTypeCatalog()
  const { data: profiles } = useProcessProfiles()
  const createDraft = useCreateCatalogDraft()
  const publish = usePublishCatalogVersion()
  const [draft, setDraft] = useState<SemanticCatalog | undefined>()
  const editing = draft !== undefined
  const catalog = draft ?? active?.catalog
  const pendingDraft = versions?.find((v) => v.status === 'draft' && v.version > (active?.version ?? 0))

  const pathsByType = useMemo(
    () => Object.fromEntries((types?.registered ?? []).map((t) => [t.name, fieldPaths(t.fields)])),
    [types],
  )

  if (isLoading || !catalog) {
    return <Loader2 className="size-5 animate-spin text-muted-foreground" />
  }
  const set = (patch: Partial<SemanticCatalog>) => setDraft({ ...catalog, ...patch })
  const attributeKeys = catalog.attributes.map((a) => a.key)
  const roleKeys = catalog.roles.map((r) => r.key)

  function save() {
    if (!draft) return
    createDraft.mutate(draft, {
      onSuccess: (row) => {
        toast.success(`Borrador v${row.version} guardado. Publícalo para que lo usen los expedientes nuevos.`)
        setDraft(undefined)
      },
      onError: (error) => toast.error(errorDetail(error)),
    })
  }

  function publishVersion(version: number) {
    publish.mutate(version, {
      onSuccess: () => toast.success(`Catálogo v${version} publicado.`),
      onError: (error) => toast.error(errorDetail(error)),
    })
  }

  const attributeColumns: Column<SemanticAttribute>[] = [
    { label: 'Clave', read: (a) => <code className="text-xs">{a.key}</code>, edit: text((a) => a.key, (a, v) => ({ ...a, key: v }), true) },
    { label: 'Nombre', read: (a) => a.name, edit: text((a) => a.name, (a, v) => ({ ...a, name: v })) },
    { label: 'Definición', read: (a) => <span className="text-muted-foreground">{a.definition}</span>, edit: text((a) => a.definition, (a, v) => ({ ...a, definition: v })) },
    { label: 'Tipo', read: (a) => a.data_type, edit: choice(['string', 'number', 'integer', 'date', 'boolean'], (a) => a.data_type, (a, v) => ({ ...a, data_type: v as SemanticAttribute['data_type'] })) },
    {
      label: 'Comparación',
      read: (a) => a.comparison + (a.tolerance ? ` ±${a.tolerance * 100}%` : ''),
      edit: choice(['identifier', 'person_name', 'company_name', 'text', 'number', 'date'], (a) => a.comparison, (a, v) => ({ ...a, comparison: v as SemanticAttribute['comparison'] })),
    },
    {
      label: 'Formato (CEL sobre value)',
      read: (a) => (a.format_cel ? <code className="text-xs">{a.format_cel}</code> : <span className="text-muted-foreground">—</span>),
      edit: text((a) => a.format_cel ?? '', (a, v) => ({ ...a, format_cel: v.trim() ? v : null }), true),
    },
    {
      label: 'PII',
      read: (a) => (a.pii_class === 'none' ? '—' : <Badge variant={a.pii_class === 'sensitive' ? 'destructive' : 'secondary'}>{a.pii_class}</Badge>),
      edit: choice(['none', 'personal', 'sensitive'], (a) => a.pii_class, (a, v) => ({ ...a, pii_class: v as SemanticAttribute['pii_class'] })),
    },
  ]

  const mappingColumns: Column<FieldMapping>[] = [
    {
      label: 'Tipo documental',
      read: (m) => <code className="text-xs">{m.document_type}</code>,
      edit: choice(Object.keys(pathsByType), (m) => m.document_type, (m, v) => ({ ...m, document_type: v, field_path: '' })),
    },
    {
      label: 'Campo(s)',
      read: (m) => <code className="text-xs">{joinPath(m.field_path)}</code>,
      edit: (m, onSet) => (
        <>
          <Input
            list={`paths-${m.document_type}`}
            value={joinPath(m.field_path)}
            onChange={(e) => onSet({ ...m, field_path: splitPath(e.target.value) })}
            placeholder="campo, o campo_a + campo_b para concatenar"
            className="font-mono text-xs"
          />
          <datalist id={`paths-${m.document_type}`}>
            {(pathsByType[m.document_type] ?? []).map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>
        </>
      ),
    },
    { label: 'Atributo', read: (m) => <Badge variant="secondary">{m.attribute}</Badge>, edit: choice(attributeKeys, (m) => m.attribute, (m, v) => ({ ...m, attribute: v })) },
    { label: 'Rol', read: (m) => m.role, edit: choice(roleKeys, (m) => m.role, (m, v) => ({ ...m, role: v })) },
  ]

  const keyNameDefinition = <T extends { key: string; name: string; definition: string }>(): Column<T>[] => [
    { label: 'Clave', read: (r) => <code className="text-xs">{r.key}</code>, edit: text((r) => r.key, (r, v) => ({ ...r, key: v }), true) },
    { label: 'Nombre', read: (r) => r.name, edit: text((r) => r.name, (r, v) => ({ ...r, name: v })) },
    { label: 'Definición', read: (r) => <span className="text-muted-foreground">{r.definition}</span>, edit: text((r) => r.definition, (r, v) => ({ ...r, definition: v })) },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Catálogo semántico</h1>
          <p className="text-muted-foreground">
            Qué significan los datos, más allá del documento que los trae: entidades, atributos, roles y qué campo de cada tipo
            documental expresa cada atributo. Cada perfil de proceso fija una versión del catálogo: una versión nueva aplica a
            un proceso cuando una versión de su perfil la adopta (ver Versiones).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">publicado v{active?.version}</Badge>
          {isAdmin() && !editing && (
            <Button onClick={() => setDraft(structuredClone(active!.catalog))}>
              <Pencil className="size-4" /> Editar
            </Button>
          )}
          {editing && (
            <>
              <Button variant="outline" onClick={() => setDraft(undefined)}>
                Descartar
              </Button>
              <Button onClick={save} disabled={createDraft.isPending}>
                {createDraft.isPending && <Loader2 className="size-4 animate-spin" />}
                Guardar borrador
              </Button>
            </>
          )}
        </div>
      </div>

      {pendingDraft && !editing && (
        <Card className="border-amber-300 bg-amber-50 dark:bg-amber-950/30">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6 text-sm">
            <span>
              Hay un borrador <strong>v{pendingDraft.version}</strong> sin publicar ({pendingDraft.created_by}).
            </span>
            {isAdmin() && (
              <Button size="sm" onClick={() => publishVersion(pendingDraft.version)} disabled={publish.isPending}>
                Publicar v{pendingDraft.version}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="mappings">
        <TabsList>
          <TabsTrigger value="mappings">Mapeos ({catalog.mappings.length})</TabsTrigger>
          <TabsTrigger value="attributes">Atributos ({catalog.attributes.length})</TabsTrigger>
          <TabsTrigger value="entities">Entidades ({catalog.entities.length})</TabsTrigger>
          <TabsTrigger value="roles">Roles ({catalog.roles.length})</TabsTrigger>
          <TabsTrigger value="versions">Versiones</TabsTrigger>
        </TabsList>
        <TabsContent value="mappings">
          <EditableTable
            rows={catalog.mappings}
            columns={mappingColumns}
            editing={editing}
            onChange={(mappings) => set({ mappings })}
            blank={(): FieldMapping => ({ document_type: '', field_path: '', attribute: '', role: '' })}
          />
        </TabsContent>
        <TabsContent value="attributes">
          <EditableTable
            rows={catalog.attributes}
            columns={attributeColumns}
            editing={editing}
            onChange={(attributes) => set({ attributes })}
            blank={(): SemanticAttribute => ({ key: '', name: '', definition: '', data_type: 'string', comparison: 'text', pii_class: 'none' })}
          />
        </TabsContent>
        <TabsContent value="entities">
          <EditableTable rows={catalog.entities} columns={keyNameDefinition()} editing={editing} onChange={(entities) => set({ entities })} blank={() => ({ key: '', name: '', definition: '' })} />
        </TabsContent>
        <TabsContent value="roles">
          <EditableTable rows={catalog.roles} columns={keyNameDefinition()} editing={editing} onChange={(roles) => set({ roles })} blank={() => ({ key: '', name: '', definition: '' })} />
        </TabsContent>
        <TabsContent value="versions">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Versión</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Creada por</TableHead>
                <TableHead>Publicada</TableHead>
                <TableHead>Perfiles que la usan</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(versions ?? []).map((v) => (
                <TableRow key={v.version}>
                  <TableCell>v{v.version}</TableCell>
                  <TableCell>
                    <Badge variant={v.status === 'published' ? 'secondary' : 'outline'}>{v.status}</Badge>
                  </TableCell>
                  <TableCell className="text-sm">{v.created_by}</TableCell>
                  <TableCell className="text-sm">{v.published_at ? new Date(v.published_at).toLocaleString() : '—'}</TableCell>
                  <TableCell className="text-sm">
                    {(profiles ?? [])
                      .filter((p) => p.versions.find((pv) => pv.version === p.active_version)?.semantic_catalog_version === v.version)
                      .map((p) => (
                        <Badge key={p.key} variant="outline" className="mr-1">
                          {p.key}
                        </Badge>
                      ))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TabsContent>
      </Tabs>
    </div>
  )
}
