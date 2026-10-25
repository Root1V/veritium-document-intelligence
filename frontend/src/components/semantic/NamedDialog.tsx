// A group of data or a person of the case, by its name and what it means
// (VRT-89); its key follows the name while it is new.
import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { slug } from '@/lib/processProfile'

interface Named {
  key: string
  name: string
  definition: string
}

export function NamedDialog({ title, hint, item, taken, inUse, onApply, onRemove, onClose }: {
  title: string
  hint: string
  /** null for a new one. */
  item: Named | null
  taken: string[]
  /** Why it can't go, when something uses it. */
  inUse: string | null
  onApply: (item: Named) => void
  onRemove: () => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState<Named>(item ?? { key: '', name: '', definition: '' })
  const problem = !draft.name.trim() ? 'Ponle un nombre.' : !draft.key ? 'El nombre necesita letras.' : !item && taken.includes(draft.key) ? 'Ya existe uno con ese nombre.' : null

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{hint}</DialogDescription>
        </DialogHeader>
        <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value, key: item ? draft.key : slug(e.target.value) })} placeholder="Nombre" />
        <Textarea value={draft.definition} onChange={(e) => setDraft({ ...draft, definition: e.target.value })} placeholder="Qué significa" className="min-h-16" />
        <p className="text-xs text-muted-foreground">
          Clave <code>{draft.key || '—'}</code>
          {item && ' (no cambia: los datos y procesos la usan)'}
        </p>
        <DialogFooter className="flex-row flex-wrap items-center gap-2 sm:justify-between">
          <span className="text-xs text-muted-foreground">
            {item &&
              (inUse ? (
                inUse
              ) : (
                <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={onRemove}>
                  <Trash2 className="size-3.5" /> Quitar
                </Button>
              ))}
            {!item && problem}
          </span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button onClick={() => onApply(draft)} disabled={!!problem}>
              Aplicar
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
