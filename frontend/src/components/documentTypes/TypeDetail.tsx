// One document type (VRT-88): every field it reads, by its name, with its
// format and what it means in the data catalog; the platform team names the
// fields here without publishing a new version.
import { useState } from 'react'
import { CornerDownRight, FileText, Loader2, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { isPlatformAdmin } from '@/lib/auth'
import { fieldName, flatten, formatOf, meaningOf } from '@/lib/documentTypes'
import { useSetFieldLabels } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { DocumentTypeInfo, SemanticCatalog } from '@/types/api'

export function TypeDetail({ type, catalog, usedBy, onClose }: {
  type: DocumentTypeInfo
  catalog: SemanticCatalog | undefined
  usedBy: string[]
  onClose: () => void
}) {
  const rows = flatten(type.fields)
  const [editing, setEditing] = useState<Record<string, string> | null>(null)
  const save = useSetFieldLabels()
  const meaningful = rows.filter((r) => meaningOf(catalog, type.name, r.path)).length

  function handleSave() {
    if (!editing) return
    const changed = Object.fromEntries(Object.entries(editing).filter(([path, label]) => label !== fieldName(rows.find((r) => r.path === path)!.field)))
    if (!Object.keys(changed).length) return setEditing(null)
    save.mutate(
      { key: type.name, labels: changed },
      {
        onSuccess: () => {
          toast.success('Nombres guardados. Ya se ven así en revisión y reportes.')
          setEditing(null)
        },
        onError: (e) => toast.error(errorDetail(e)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-4 sm:max-w-4xl">
        <DialogHeader>
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <FileText className="size-5" />
            </span>
            <div className="flex min-w-0 flex-col gap-1 text-left">
              <DialogTitle>{type.display_name}</DialogTitle>
              <DialogDescription className="first-letter:uppercase">{type.description}</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full bg-muted px-2.5 py-1">{rows.length} datos</span>
          <span className="rounded-full bg-muted px-2.5 py-1">{rows.filter((r) => r.field.required).length} siempre presentes</span>
          <span className="rounded-full bg-muted px-2.5 py-1">{meaningful} con significado en el catálogo</span>
          <span className="rounded-full bg-muted px-2.5 py-1">{usedBy.length ? `Lo piden: ${usedBy.join(', ')}` : 'Ningún proceso lo pide'}</span>
        </div>

        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Datos que lee</h3>
          {isPlatformAdmin() &&
            (editing ? (
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)} disabled={save.isPending}>
                  Cancelar
                </Button>
                <Button size="sm" onClick={handleSave} disabled={save.isPending}>
                  {save.isPending && <Loader2 className="size-3.5 animate-spin" />} Guardar nombres
                </Button>
              </div>
            ) : (
              <Button size="sm" variant="outline" onClick={() => setEditing(Object.fromEntries(rows.map((r) => [r.path, fieldName(r.field)])))}>
                <Pencil className="size-3.5" /> Editar nombres
              </Button>
            ))}
        </div>

        <div className="-mx-6 min-h-0 flex-1 overflow-y-auto border-y">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-background text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="px-6 py-2 text-left font-medium">Dato</th>
                <th className="px-3 py-2 text-left font-medium">Formato</th>
                <th className="px-6 py-2 text-left font-medium">Significado</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ path, field, depth }) => {
                const meaning = meaningOf(catalog, type.name, path)
                return (
                  <tr key={path} className="border-b align-top last:border-0">
                    <td className={cn('px-6 py-2.5', depth && 'pl-10')}>
                      <div className="flex items-start gap-1.5">
                        {depth === 1 && <CornerDownRight className="mt-1 size-3.5 shrink-0 text-muted-foreground" />}
                        <div className="flex min-w-0 flex-col gap-0.5">
                          {editing ? (
                            <Input
                              value={editing[path] ?? ''}
                              onChange={(e) => setEditing({ ...editing, [path]: e.target.value })}
                              className="h-8"
                              aria-label={`Nombre de ${field.name}`}
                            />
                          ) : (
                            <span className="font-medium">
                              {fieldName(field)}
                              {field.required && <span className="ml-1.5 text-xs font-normal text-muted-foreground">· siempre presente</span>}
                            </span>
                          )}
                          {field.description && <span className="text-xs text-muted-foreground">{field.description}</span>}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-xs whitespace-nowrap text-muted-foreground">{formatOf(field)}</td>
                    <td className="px-6 py-2.5 text-xs">{meaning ? <span className="rounded-md bg-primary/10 px-2 py-0.5 text-primary">{meaning}</span> : <span className="text-muted-foreground">—</span>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <details className="text-xs text-muted-foreground">
          <summary className="w-fit cursor-pointer select-none hover:text-foreground">Detalle técnico</summary>
          <p className="mt-2">
            Clave <code>{type.name}</code> · versión {type.version}. La descripción de arriba es la que usa el clasificador para reconocer el documento. Los
            nombres técnicos de cada dato: {rows.map((r) => r.path).join(', ')}.
          </p>
        </details>
      </DialogContent>
    </Dialog>
  )
}
