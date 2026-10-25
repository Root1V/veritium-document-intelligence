// One reading of Risk or Legal, created or edited in one place (VRT-91):
// who it is for, what it reads, and either what the summary focuses on or
// each point a document must meet, with its importance.
import { useState } from 'react'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { DeleteButton } from '@/components/DeleteButton'
import { errorDetail } from '@/lib/apiErrors'
import { AREA, IMPORTANCE } from '@/lib/lenses'
import { slug } from '@/lib/processProfile'
import { useSaveLens } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { DocumentTypeInfo, LensDefinition, PlaybookItem } from '@/types/api'

/** A snake_case key the API accepts, not taken yet. */
function keyFrom(text: string, taken: string[], fallback: string): string {
  const base = slug(text).slice(0, 40) || fallback
  const key = /^[a-z]/.test(base) ? base : `${fallback}_${base}`
  let candidate = key
  for (let n = 2; taken.includes(candidate); n++) candidate = `${key}_${n}`
  return candidate
}

function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string; className?: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded-md border px-2.5 py-1 text-xs transition',
            value === o.value ? cn('border-current font-medium', o.className ?? 'bg-primary/10 text-primary') : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function LensDialog({ lens, area, taken, types, onClose }: {
  /** null for a new one of `area`. */
  lens: LensDefinition | null
  area: LensDefinition['area']
  taken: string[]
  types: DocumentTypeInfo[]
  onClose: () => void
}) {
  const save = useSaveLens()
  const isNew = lens === null
  const [draft, setDraft] = useState<LensDefinition>(
    lens ?? { key: '', name: '', area, description: '', kind: area === 'legal' ? 'playbook' : 'summary', document_types: [], instructions: '', playbook: [] },
  )
  const set = (patch: Partial<LensDefinition>) => setDraft({ ...draft, ...patch })
  const setPoint = (i: number, patch: Partial<PlaybookItem>) => set({ playbook: draft.playbook.map((p, j) => (j === i ? { ...p, ...patch } : p)) })
  const addPoint = () =>
    set({ playbook: [...draft.playbook, { key: keyFrom(`punto ${draft.playbook.length + 1}`, draft.playbook.map((p) => p.key), 'punto'), label: '', guidance: '', importance: 'media' }] })
  const toggleType = (key: string) =>
    set({ document_types: draft.document_types.includes(key) ? draft.document_types.filter((t) => t !== key) : [...draft.document_types, key] })

  const problem = !draft.name.trim()
    ? 'Ponle un nombre.'
    : draft.kind === 'summary' && !draft.instructions.trim()
      ? 'Di en qué se enfoca el resumen.'
      : draft.kind === 'playbook' && !draft.playbook.length
        ? 'Agrega al menos un punto que deba cumplirse.'
        : draft.kind === 'playbook' && draft.playbook.some((p) => !p.label.trim())
          ? 'Cada punto necesita decir qué debe cumplirse.'
          : null

  function submit() {
    // Points named after what they check, so a reading's record says it in words.
    const playbook = draft.playbook.map((p, i, all) =>
      p.key.startsWith('punto') && p.label.trim() ? { ...p, key: keyFrom(p.label, all.filter((_, j) => j !== i).map((x) => x.key), 'punto') } : p,
    )
    const next = { ...draft, playbook: draft.kind === 'playbook' ? playbook : [], key: isNew ? keyFrom(`${draft.area} ${draft.name}`, taken, draft.area) : draft.key }
    save.mutate(next, {
      onSuccess: () => {
        toast.success(isNew ? 'Lectura creada. Ya se ofrece en los expedientes.' : 'Cambios guardados. Las próximas lecturas los usan.')
        onClose()
      },
      onError: (e) => toast.error(errorDetail(e)),
    })
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>{isNew ? `Nueva lectura para ${AREA[draft.area].name}` : lens.name}</DialogTitle>
          <DialogDescription>{AREA[draft.area].hint}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 py-5">
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Qué es</h3>
            <Input value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder={draft.kind === 'playbook' ? 'p. ej. Carta de autorización de descuento' : 'p. ej. Resumen crediticio'} />
            <Input value={draft.description} onChange={(e) => set({ description: e.target.value })} placeholder="Para qué sirve, en una frase (opcional)" />
            {isNew && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                Entrega
                <Segmented
                  value={draft.kind}
                  options={[
                    { value: 'summary', label: 'Un resumen del expediente' },
                    { value: 'playbook', label: 'Una revisión punto por punto' },
                  ]}
                  onChange={(kind) => set({ kind })}
                />
              </div>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <div>
              <h3 className="text-sm font-semibold">Qué documentos lee</h3>
              <p className="text-xs text-muted-foreground">{draft.document_types.length ? 'Solo los marcados.' : 'Ninguno marcado: lee todo el expediente.'}</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {types.map((t) => {
                const on = draft.document_types.includes(t.name)
                return (
                  <button
                    key={t.name}
                    type="button"
                    onClick={() => toggleType(t.name)}
                    className={cn('rounded-full border px-2.5 py-1 text-xs transition', on ? 'border-primary bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:text-foreground')}
                  >
                    {t.display_name}
                  </button>
                )
              })}
            </div>
          </section>

          {draft.kind === 'summary' ? (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold">En qué se enfoca el resumen</h3>
              <Textarea
                rows={5}
                value={draft.instructions}
                onChange={(e) => set({ instructions: e.target.value })}
                placeholder="p. ej. Quién es el titular y su empleador; ingresos y descuentos; monto, plazo y cuota; señales de alerta."
              />
            </section>
          ) : (
            <section className="flex flex-col gap-2">
              <div>
                <h3 className="text-sm font-semibold">Lo que el documento debe cumplir</h3>
                <p className="text-xs text-muted-foreground">Cada punto se revisa en el documento y se responde con la cita que lo prueba.</p>
              </div>
              {draft.playbook.map((p, i) => (
                <div key={p.key} className="flex flex-col gap-2 rounded-lg border bg-card p-3">
                  <div className="flex items-center gap-2">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">{i + 1}</span>
                    <Input value={p.label} onChange={(e) => setPoint(i, { label: e.target.value })} placeholder="Qué debe cumplirse, p. ej. Está firmada por el titular" className="h-9" />
                    <Button variant="ghost" size="icon" className="size-8 shrink-0 text-muted-foreground" onClick={() => set({ playbook: draft.playbook.filter((_, j) => j !== i) })} aria-label="Quitar punto">
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                  <div className="flex flex-col gap-2 pl-8">
                    <Input value={p.guidance} onChange={(e) => setPoint(i, { guidance: e.target.value })} placeholder="Cómo saber si cumple (opcional)" className="h-8 text-xs" />
                    <Segmented
                      value={p.importance}
                      options={(Object.keys(IMPORTANCE) as PlaybookItem['importance'][]).map((k) => ({ value: k, label: IMPORTANCE[k].label, className: IMPORTANCE[k].chip }))}
                      onChange={(importance) => setPoint(i, { importance })}
                    />
                  </div>
                </div>
              ))}
              <Button variant="outline" size="sm" className="self-start" onClick={addPoint}>
                <Plus className="size-3.5" /> Agregar punto
              </Button>
            </section>
          )}
        </div>

        <DialogFooter className="flex-row flex-wrap items-center gap-2 border-t px-6 py-4 sm:justify-between">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {!isNew && (
              <DeleteButton
                label="Eliminar"
                path={`/v1/lenses/${lens.key}`}
                question={`¿Eliminar «${lens.name}»? Deja de ofrecerse en los expedientes; las lecturas ya hechas se conservan.`}
                onDone={onClose}
              />
            )}
            {problem}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button onClick={submit} disabled={!!problem || save.isPending}>
              {save.isPending && <Loader2 className="size-4 animate-spin" />} {isNew ? 'Crear' : 'Guardar'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
