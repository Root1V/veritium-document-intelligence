// Creating a business unit or changing its name (VRT-57, VRT-101). A new
// unit ends on the groups to create in the corporate account — nobody gets
// in until they exist. Deleting one, which only works without cases, sits at
// the bottom of the edit.
import { useState } from 'react'
import { Copy, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useDeleteAction } from '@/components/DeleteButton'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { useBusinessUnitAction } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { BusinessUnitView } from '@/types/api'

const ROLE_LABEL: Record<string, string> = { admin: 'Admin', operador: 'Operador', visor: 'Visor', especialista_ia: 'Especialista IA' }

/** "Banca Corporativa" → "banca-corporativa": what goes in the groups. */
const toKey = (name: string) =>
  name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)

export function Groups({ unit }: { unit: BusinessUnitView }) {
  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast.success('Copiado.'))
  return (
    <div className="flex flex-col gap-1.5">
      {unit.groups.map((g) => (
        <div key={g} className="flex items-center gap-2 text-xs">
          <span className="w-24 shrink-0 text-muted-foreground">{ROLE_LABEL[g.split(':').pop() ?? ''] ?? ''}</span>
          <code className="truncate">{g}</code>
          <button type="button" aria-label={`Copiar ${g}`} onClick={() => copy(g)} className="text-muted-foreground hover:text-foreground">
            <Copy className="size-3" />
          </button>
        </div>
      ))}
    </div>
  )
}

const STARTS = [
  { examples: false, label: 'En blanco', hint: 'Solo el proceso interno «Ad-hoc», que usa la carga directa.' },
  { examples: true, label: 'Con procesos de ejemplo', hint: 'Para probar la unidad antes de armar sus propios procesos.' },
]

export function UnitDialog({ unit, onClose }: { unit: BusinessUnitView | null; onClose: () => void }) {
  const action = useBusinessUnitAction()
  const remove = useDeleteAction({
    path: `/v1/tenants/${unit?.key}`,
    question: `¿Eliminar la unidad «${unit?.name}»? Solo se puede si no tiene expedientes: se borran sus procesos, sistemas conectados y accesos.`,
    onDone: onClose,
  })
  const [name, setName] = useState(unit?.name ?? '')
  const [key, setKey] = useState<string | null>(null)
  const [examples, setExamples] = useState(false)
  const [created, setCreated] = useState<BusinessUnitView | null>(null)
  const shownKey = key ?? toKey(name)
  const problem = name.trim().length < 2 ? 'Ponle un nombre.' : unit ? (name.trim() === unit.name ? 'Escribe el nuevo nombre.' : null) : !shownKey ? 'Falta el identificador.' : null

  const save = () =>
    unit
      ? action.mutate(
          { kind: 'rename', key: unit.key, name: name.trim() },
          {
            onSuccess: () => {
              toast.success('Nombre actualizado.')
              onClose()
            },
            onError: (e) => toast.error(errorDetail(e)),
          },
        )
      : action.mutate({ kind: 'create', key: shownKey, name: name.trim(), examples }, { onSuccess: setCreated, onError: (e) => toast.error(errorDetail(e)) })

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>{created ? `«${created.name}» está lista` : unit ? unit.name : 'Nueva unidad'}</DialogTitle>
          <DialogDescription>
            {created
              ? 'Nadie entra hasta que exista su grupo: créalos en la cuenta corporativa y agrega a cada persona al de su rol.'
              : unit
                ? 'El identificador no cambia: es el que usan sus grupos.'
                : 'Ve solo sus expedientes, procesos, sistemas conectados y revisiones.'}
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          {created ? (
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">Grupos a crear en la cuenta corporativa</span>
              <Groups unit={created} />
            </div>
          ) : (
            <>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Nombre</span>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="p. ej. Banca Corporativa" autoFocus />
              </label>
              {unit ? (
                <p className="text-sm text-muted-foreground">
                  Identificador: <code className="text-foreground">{unit.key}</code>
                </p>
              ) : (
                <>
                  <details className="text-sm" open={key !== null}>
                    <summary className="cursor-pointer text-muted-foreground select-none hover:text-foreground">
                      Identificador: <code className="text-foreground">{shownKey || '—'}</code>
                    </summary>
                    <label className="mt-2 flex flex-col gap-1.5">
                      <span className="text-xs text-muted-foreground">Va en el nombre de sus grupos y no se puede cambiar después.</span>
                      <Input value={shownKey} onChange={(e) => setKey(e.target.value)} className="font-mono" />
                    </label>
                  </details>
                  <div className="flex flex-col gap-2">
                    <span className="text-sm font-medium">Cómo empieza</span>
                    {STARTS.map((s) => {
                      const chosen = examples === s.examples
                      return (
                        <button
                          key={s.label}
                          type="button"
                          onClick={() => setExamples(s.examples)}
                          className={cn('flex items-start gap-3 rounded-lg border p-3 text-left transition', chosen ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:border-primary/40')}
                        >
                          <span className={cn('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border', chosen && 'border-primary bg-primary')}>
                            {chosen && <span className="size-1.5 rounded-full bg-primary-foreground" />}
                          </span>
                          <span className="flex flex-col">
                            <span className="text-sm font-medium">{s.label}</span>
                            <span className="text-xs text-muted-foreground">{s.hint}</span>
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        <DialogFooter className="flex-row items-center gap-2 border-t px-6 py-4 sm:justify-between">
          {created ? (
            <>
              <span />
              <Button onClick={onClose}>Listo</Button>
            </>
          ) : (
            <>
              {unit ? (
                <Button variant="ghost" className="text-destructive" disabled={remove.pending} onClick={remove.run}>
                  Eliminar unidad
                </Button>
              ) : (
                <span className="text-xs text-muted-foreground">{problem}</span>
              )}
              <div className="flex gap-2">
                <Button variant="ghost" onClick={onClose}>
                  Cancelar
                </Button>
                <Button disabled={!!problem || action.isPending} onClick={save} title={problem ?? undefined}>
                  {action.isPending && <Loader2 className="size-4 animate-spin" />} {unit ? 'Guardar' : 'Crear unidad'}
                </Button>
              </div>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
