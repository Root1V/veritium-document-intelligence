// One datum of a proposed document type (VRT-33, VRT-88): its name in
// Spanish first, its format and whether it is always there, what it means in
// the data catalog — kept or dropped with one click — and, folded, how the
// reader finds it and its technical name.
import { useState } from 'react'
import { ChevronDown, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Choice } from '@/components/profiles/RequirementRow'
import { FORMAT } from '@/lib/documentTypes'
import { slug } from '@/lib/processProfile'
import { cn } from '@/lib/utils'
import type { FieldSpec, FieldSpecType } from '@/types/api'

export interface Meaning {
  index: number
  label: string
  accepted: boolean
}

const LEAF: FieldSpecType[] = ['str', 'int', 'float', 'bool', 'enum']

export function FieldEditor({ field, meanings, onChange, onRemove, onToggleMeaning, nested = false }: {
  field: FieldSpec
  /** What the proposal says this datum means, by the mapping's index. */
  meanings: (path: string) => Meaning[]
  onChange: (field: FieldSpec) => void
  onRemove: () => void
  onToggleMeaning: (index: number) => void
  nested?: boolean
}) {
  const [open, setOpen] = useState(false)
  const types = nested ? LEAF : [...LEAF, 'list' as FieldSpecType]
  const own = meanings(field.name)
  const setLabel = (label: string) => onChange({ ...field, label, name: !field.name || field.name === slug(field.label ?? '') ? slug(label) : field.name })
  function setType(type: FieldSpecType) {
    onChange({
      ...field,
      type,
      required: type === 'list' ? false : field.required,
      enum_values: type === 'enum' ? (field.enum_values ?? []) : null,
      item_name: type === 'list' ? (field.item_name ?? 'Fila') : null,
      items: type === 'list' ? (field.items ?? [{ name: 'valor', label: 'Valor', type: 'str', required: true, description: '' }]) : null,
    })
    if (type === 'enum' || type === 'list') setOpen(true)
  }

  return (
    <div className={cn('flex flex-col gap-2', nested ? 'border-l-2 pl-3' : 'rounded-lg border bg-card p-3')}>
      <div className="flex flex-wrap items-center gap-2">
        <Input value={field.label ?? ''} onChange={(e) => setLabel(e.target.value)} placeholder="Nombre del dato, p. ej. DNI del socio" className="h-9 min-w-48 flex-1" />
        <Choice value={field.type} className="w-44" options={types.map((t) => ({ value: t, label: FORMAT[t] }))} onChange={(v) => setType(v as FieldSpecType)} />
        {field.type !== 'list' && (
          <label className="flex items-center gap-1.5 text-xs whitespace-nowrap">
            <input type="checkbox" checked={field.required} onChange={(e) => onChange({ ...field, required: e.target.checked })} /> Siempre presente
          </label>
        )}
        <Button variant="ghost" size="icon" className="size-8 text-muted-foreground" onClick={() => setOpen(!open)} aria-label="Más detalles" aria-expanded={open}>
          <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} />
        </Button>
        <Button variant="ghost" size="icon" className="size-8 text-muted-foreground" onClick={onRemove} aria-label="Quitar dato">
          <Trash2 className="size-4" />
        </Button>
      </div>

      {own.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Significa</span>
          {own.map((m) => (
            <button
              key={m.index}
              type="button"
              onClick={() => onToggleMeaning(m.index)}
              title={m.accepted ? 'Clic para no vincularlo' : 'Clic para vincularlo'}
              className={cn(
                'rounded-md px-2 py-0.5 transition',
                m.accepted ? 'bg-primary/10 text-primary' : 'text-muted-foreground line-through decoration-muted-foreground/60 hover:text-foreground',
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
      )}

      {!open && field.description && <p className="line-clamp-1 text-xs text-muted-foreground">{field.description}</p>}

      {open && (
        <div className="flex flex-col gap-2">
          <Textarea
            value={field.description ?? ''}
            onChange={(e) => onChange({ ...field, description: e.target.value })}
            placeholder="Qué es y dónde aparece en el documento. Es lo que lee Veritium para encontrarlo."
            className="min-h-16 text-xs"
          />
          {field.type === 'enum' && (
            <Input
              value={(field.enum_values ?? []).join(', ')}
              onChange={(e) => onChange({ ...field, enum_values: e.target.value.split(',').map((v) => v.trim()).filter(Boolean) })}
              placeholder="Opciones posibles, separadas por coma"
              className="h-8 text-xs"
            />
          )}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Nombre técnico</span>
            <Input value={field.name} onChange={(e) => onChange({ ...field, name: e.target.value })} className="h-7 w-56 font-mono text-xs" />
          </div>
          {field.type === 'list' && (
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium">Columnas de la tabla</span>
              {(field.items ?? []).map((item, i) => (
                <FieldEditor
                  key={i}
                  nested
                  field={item}
                  meanings={(name) => meanings(`${field.name}[].${name}`)}
                  onToggleMeaning={onToggleMeaning}
                  onChange={(next) => onChange({ ...field, items: (field.items ?? []).map((it, j) => (j === i ? next : it)) })}
                  onRemove={() => onChange({ ...field, items: (field.items ?? []).filter((_, j) => j !== i) })}
                />
              ))}
              <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => onChange({ ...field, items: [...(field.items ?? []), { name: '', label: '', type: 'str', required: false, description: '' }] })}
              >
                <Plus className="size-3.5" /> Columna
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
