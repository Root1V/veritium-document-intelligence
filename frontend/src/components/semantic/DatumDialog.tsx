// One datum of the catalog, edited in words (VRT-89): what it is, how it is
// compared between documents, how private it is and which documents bring
// it. The change goes into the page's draft; nothing is saved until the
// page saves it.
import { useState } from 'react'
import { Plus, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Choice } from '@/components/profiles/RequirementRow'
import { slug } from '@/lib/processProfile'
import { COMPARISON, DATA_TYPE, PII, fieldOptions } from '@/lib/semanticCatalog'
import { cn } from '@/lib/utils'
import type { DocumentTypeInfo, FieldMapping, PiiClass, SemanticAttribute, SemanticCatalog, SemanticComparison, SemanticDataType } from '@/types/api'

const paths = (p: string | string[]) => (Array.isArray(p) ? p : [p])

export function DatumDialog({ catalog, attribute, entity, types, usedBy, onApply, onClose }: {
  catalog: SemanticCatalog
  /** null for a new datum of `entity`. */
  attribute: SemanticAttribute | null
  entity: string
  types: DocumentTypeInfo[]
  usedBy: string[]
  onApply: (catalog: SemanticCatalog) => void
  onClose: () => void
}) {
  const isNew = attribute === null
  const [datum, setDatum] = useState<SemanticAttribute>(
    attribute ?? { key: `${entity}.`, name: '', definition: '', data_type: 'string', comparison: 'text', pii_class: 'personal' }, // private until someone says otherwise (VRT-58)
  )
  const [sources, setSources] = useState<FieldMapping[]>(attribute ? catalog.mappings.filter((m) => m.attribute === attribute.key) : [])
  const [confirmRemove, setConfirmRemove] = useState(false)
  const typeOf = (key: string) => types.find((t) => t.name === key)
  const set = (patch: Partial<SemanticAttribute>) => setDatum({ ...datum, ...patch })
  const setSource = (i: number, patch: Partial<FieldMapping>) => setSources(sources.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  const [keyTouched, setKeyTouched] = useState(false)

  const problems = [
    !datum.name.trim() && 'Ponle un nombre.',
    !datum.definition.trim() && 'Explica qué es: es lo que leen las personas y Veritium.',
    isNew && catalog.attributes.some((a) => a.key === datum.key) && 'Ya hay un dato con ese nombre en este grupo.',
    sources.some((s) => !s.document_type || !paths(s.field_path).every(Boolean) || !s.role) && 'Completa cada documento: cuál, qué campo y de quién.',
  ].filter(Boolean) as string[]

  function apply() {
    const others = catalog.mappings.filter((m) => m.attribute !== attribute?.key)
    onApply({
      ...catalog,
      attributes: isNew ? [...catalog.attributes, datum] : catalog.attributes.map((a) => (a.key === attribute.key ? datum : a)),
      mappings: [...others, ...sources.map((s) => ({ ...s, attribute: datum.key }))],
    })
  }

  function remove() {
    onApply({
      ...catalog,
      attributes: catalog.attributes.filter((a) => a.key !== attribute!.key),
      mappings: catalog.mappings.filter((m) => m.attribute !== attribute!.key),
    })
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-3xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>{isNew ? `Nuevo dato de ${catalog.entities.find((e) => e.key === entity)?.name ?? entity}` : attribute.name}</DialogTitle>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 py-5">
          <section className="flex flex-col gap-3">
            <h3 className="text-sm font-semibold">Qué es</h3>
            <Input value={datum.name} onChange={(e) => set({ name: e.target.value, ...(isNew && !keyTouched && { key: `${entity}.${slug(e.target.value)}` }) })} placeholder="Nombre del dato, p. ej. Ingreso neto mensual" />
            <Textarea
              value={datum.definition}
              onChange={(e) => set({ definition: e.target.value })}
              placeholder="Qué significa, en palabras del negocio. Veritium también lo lee para entender el dato."
              className="min-h-16"
            />
          </section>

          <section className="flex flex-col gap-3">
            <h3 className="text-sm font-semibold">Cómo es</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
                Formato
                <Choice value={datum.data_type} options={Object.entries(DATA_TYPE).map(([value, label]) => ({ value, label }))} onChange={(v) => set({ data_type: v as SemanticDataType })} />
              </label>
              <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
                Al comparar entre documentos
                <div className="flex gap-2">
                  <Choice
                    value={datum.comparison}
                    className="flex-1"
                    options={Object.entries(COMPARISON).map(([value, label]) => ({ value, label }))}
                    onChange={(v) => set({ comparison: v as SemanticComparison, tolerance: v === 'number' ? datum.tolerance : null })}
                  />
                  {datum.comparison === 'number' && (
                    <span className="flex items-center gap-1 text-foreground">
                      ±
                      <Input
                        type="number"
                        min={0}
                        step={0.1}
                        value={datum.tolerance ? +(datum.tolerance * 100).toFixed(2) : ''}
                        onChange={(e) => set({ tolerance: e.target.value ? Number(e.target.value) / 100 : null })}
                        className="h-9 w-20"
                        aria-label="Margen en porcentaje"
                      />
                      %
                    </span>
                  )}
                </div>
              </label>
            </div>
            <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Privacidad
              <div className="flex flex-wrap gap-2">
                {(Object.keys(PII) as PiiClass[]).map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => set({ pii_class: p })}
                    className={cn(
                      'rounded-md border px-3 py-1.5 text-sm transition',
                      datum.pii_class === p ? cn(PII[p].className, 'border-current font-medium') : 'text-muted-foreground hover:text-foreground',
                    )}
                  >
                    {PII[p].label}
                  </button>
                ))}
              </div>
              <span>Los datos personales y sensibles se ocultan a quien no debe verlos.</span>
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <div>
              <h3 className="text-sm font-semibold">De qué documentos sale</h3>
              <p className="text-xs text-muted-foreground">Si dos documentos lo traen, Veritium compara sus valores y avisa si no coinciden.</p>
            </div>
            {sources.map((s, i) => {
              const options = fieldOptions(typeOf(s.document_type))
              return (
                <div key={i} className="flex flex-wrap items-start gap-2 rounded-lg border bg-card p-3">
                  <Choice
                    value={s.document_type}
                    placeholder="Documento"
                    className="w-64"
                    options={types.map((t) => ({ value: t.name, label: t.display_name }))}
                    onChange={(v) => setSource(i, { document_type: v, field_path: '' })}
                  />
                  <div className="flex min-w-52 flex-1 flex-col gap-1.5">
                    {paths(s.field_path).map((p, k, all) => (
                      <div key={k} className="flex items-center gap-1.5">
                        {k > 0 && <span className="text-xs text-muted-foreground">+</span>}
                        <Choice
                          value={p}
                          placeholder={s.document_type ? 'Campo' : 'Elige el documento'}
                          className="flex-1"
                          options={options}
                          onChange={(v) => setSource(i, { field_path: all.length > 1 ? all.map((x, j) => (j === k ? v : x)) : v })}
                        />
                        {k > 0 && (
                          <Button variant="ghost" size="icon" className="size-7" onClick={() => setSource(i, { field_path: all.length > 2 ? all.filter((_, j) => j !== k) : all[0] })} aria-label="Quitar campo">
                            <X className="size-3.5" />
                          </Button>
                        )}
                      </div>
                    ))}
                    {s.document_type && (
                      <button type="button" className="self-start text-xs text-muted-foreground hover:text-foreground" onClick={() => setSource(i, { field_path: [...paths(s.field_path), ''] })}>
                        + Unir con otro campo (p. ej. nombres + apellidos)
                      </button>
                    )}
                  </div>
                  <Choice value={s.role} placeholder="De quién" className="w-36" options={catalog.roles.map((r) => ({ value: r.key, label: r.name }))} onChange={(v) => setSource(i, { role: v })} />
                  <Button variant="ghost" size="icon" className="size-9 text-muted-foreground" onClick={() => setSources(sources.filter((_, j) => j !== i))} aria-label="Quitar documento">
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              )
            })}
            <Button variant="outline" size="sm" className="self-start" onClick={() => setSources([...sources, { document_type: '', field_path: '', attribute: datum.key, role: 'titular' }])}>
              <Plus className="size-3.5" /> Agregar documento
            </Button>
          </section>

          <details className="text-xs text-muted-foreground">
            <summary className="w-fit cursor-pointer select-none hover:text-foreground">Detalle técnico</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                Clave {!isNew && '(no cambia: los procesos la usan)'}
                <Input value={datum.key} disabled={!isNew} onChange={(e) => (setKeyTouched(true), set({ key: e.target.value }))} className="h-8 font-mono text-xs" />
              </label>
              <label className="flex flex-col gap-1.5">
                Regla de formato (CEL sobre value)
                <Input value={datum.format_cel ?? ''} onChange={(e) => set({ format_cel: e.target.value.trim() ? e.target.value : null })} placeholder="p. ej. value.matches('^[0-9]{8}$')" className="h-8 font-mono text-xs" />
              </label>
            </div>
          </details>
        </div>

        <DialogFooter className="flex-row flex-wrap items-center gap-2 border-t px-6 py-4 sm:justify-between">
          <div className="text-xs">
            {!isNew &&
              (confirmRemove ? (
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-destructive">{usedBy.length ? `Lo usan ${usedBy.join(', ')}: dejarán de encontrarlo cuando adopten esta versión.` : '¿Quitar este dato del catálogo?'}</span>
                  <Button size="sm" variant="destructive" onClick={remove}>
                    Quitar
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(false)}>
                    No
                  </Button>
                </span>
              ) : (
                <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={() => setConfirmRemove(true)}>
                  <Trash2 className="size-3.5" /> Quitar dato
                </Button>
              ))}
            {problems.length > 0 && <span className="text-muted-foreground">{problems[0]}</span>}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button onClick={apply} disabled={problems.length > 0}>
              Aplicar
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
