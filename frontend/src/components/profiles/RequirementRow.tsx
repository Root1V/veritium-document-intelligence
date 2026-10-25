// One thing a process asks for (VRT-80, VRT-87): a document type, or a data
// item any document may bring; and when it is asked — always, if it applies,
// or under a condition.
import { FileText, Trash2, Variable } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { slug, whenOf } from '@/lib/processProfile'
import type { ChecklistItem, ProfileLibrary } from '@/types/api'

export function Choice({ value, options, onChange, placeholder, className }: {
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={cn('h-9', className)}>
        <SelectValue placeholder={placeholder ?? '—'} />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function RequirementRow({ index, item, library, onChange, onRemove }: {
  index: number
  item: ChecklistItem
  library: ProfileLibrary
  onChange: (item: ChecklistItem) => void
  onRemove: () => void
}) {
  const byType = item.document_type != null
  const attribute = item.requires_attributes[0] ?? ''
  const typeName = (key: string) => library.document_types.find((t) => t.key === key)?.display_name ?? key
  const providers = library.attributes.find((a) => a.key === attribute)?.providers.filter((p) => p.role === item.role) ?? []
  const when = whenOf(item)
  // The name follows the choice until the person writes their own.
  const named = (label: string, previous: string) => (!item.label || item.label === previous ? { label, key: slug(label) } : {})
  const setLabel = (label: string) => onChange({ ...item, label, key: !item.key || item.key === slug(item.label) ? slug(label) : item.key })

  return (
    <div className="flex gap-3 rounded-lg border bg-card p-3">
      <span className="mt-1.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">{index + 1}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <Input value={item.label} onChange={(e) => setLabel(e.target.value)} placeholder="Qué se pide, p. ej. Boleta de pago del titular" className="h-9 min-w-56 flex-1" />
          <Choice
            value={when}
            className="w-48"
            options={[
              { value: 'always', label: 'Siempre se exige' },
              { value: 'optional', label: 'Solo si aplica' },
              { value: 'condition', label: 'Con una condición' },
            ]}
            onChange={(v) =>
              onChange({ ...item, required: v !== 'optional', required_when_cel: v === 'condition' ? (item.required_when_cel ?? '') : null })
            }
          />
          <Button variant="ghost" size="icon" className="size-9 text-muted-foreground" onClick={onRemove} aria-label="Quitar requisito">
            <Trash2 className="size-4" />
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-md border p-0.5" role="radiogroup" aria-label="Qué lo cumple">
            {[
              { value: true, label: 'Un documento', icon: FileText },
              { value: false, label: 'Un dato', icon: Variable },
            ].map(({ value, label, icon: Icon }) => (
              <button
                key={label}
                type="button"
                role="radio"
                aria-checked={byType === value}
                onClick={() =>
                  byType !== value &&
                  onChange(value ? { ...item, document_type: '', requires_attributes: [], accepted_document_types: null } : { ...item, document_type: null, requires_attributes: [''] })
                }
                className={cn(
                  'inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors',
                  byType === value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <Icon className="size-3.5" /> {label}
              </button>
            ))}
          </div>
          {byType ? (
            <Choice
              value={item.document_type ?? ''}
              placeholder="Elige el tipo de documento"
              className="w-72"
              options={library.document_types.map((t) => ({ value: t.key, label: t.display_name }))}
              onChange={(v) => onChange({ ...item, document_type: v, ...named(typeName(v), typeName(item.document_type ?? '')) })}
            />
          ) : (
            <>
              <Choice
                value={attribute}
                placeholder="Elige el dato"
                className="w-64"
                options={library.attributes.filter((a) => a.providers.length).map((a) => ({ value: a.key, label: a.name }))}
                onChange={(v) => onChange({ ...item, requires_attributes: [v] })}
              />
              <span className="text-xs text-muted-foreground">de</span>
              <Choice value={item.role} className="w-36" options={library.roles.map((r) => ({ value: r.key, label: r.name.toLowerCase() }))} onChange={(v) => onChange({ ...item, role: v })} />
            </>
          )}
        </div>

        {!byType && attribute && (
          <p className={cn('text-xs', providers.length ? 'text-muted-foreground' : 'text-amber-700 dark:text-amber-400')}>
            {providers.length ? `Lo cumple cualquiera de: ${providers.map((p) => typeName(p.document_type)).join(', ')}.` : 'Ningún tipo de documento trae ese dato para esa persona.'}
          </p>
        )}

        {when === 'condition' && (
          <div className="flex flex-col gap-1">
            <Input
              value={item.required_when_cel ?? ''}
              onChange={(e) => onChange({ ...item, required_when_cel: e.target.value })}
              placeholder="request.nacionalidad != 'PE'"
              className="h-8 font-mono text-xs"
              aria-label="Condición"
            />
            <span className="text-xs text-muted-foreground">Se exige solo cuando se cumple. Puede usar los datos de la solicitud (request.…) o del expediente (case.…).</span>
          </div>
        )}
      </div>
    </div>
  )
}
