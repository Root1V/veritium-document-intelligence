// The words of the data catalog page (VRT-89): what a setting of a datum
// means, and a field of a document type by its name instead of its path.
import { fieldName } from '@/lib/documentTypes'
import type { DocumentTypeInfo, PiiClass, SemanticComparison, SemanticDataType } from '@/types/api'

export const DATA_TYPE: Record<SemanticDataType, string> = { string: 'Texto', number: 'Número o monto', integer: 'Número entero', date: 'Fecha', boolean: 'Sí / No' }

export const COMPARISON: Record<SemanticComparison, string> = {
  identifier: 'Exacto, como un código',
  person_name: 'Parecido, como nombre de persona',
  company_name: 'Parecido, como nombre de empresa',
  text: 'Texto igual',
  number: 'Como número',
  date: 'Como fecha',
}

export const PII: Record<PiiClass, { label: string; className: string }> = {
  none: { label: 'No es personal', className: 'bg-muted text-muted-foreground' },
  personal: { label: 'Dato personal', className: 'bg-amber-500/10 text-amber-700 dark:text-amber-400' },
  sensitive: { label: 'Dato sensible', className: 'bg-red-500/10 text-red-700 dark:text-red-400' },
}

/** Every field a mapping can read, by its name: a table column reads through its first row. */
export function fieldOptions(type: DocumentTypeInfo | undefined): { value: string; label: string }[] {
  return (type?.fields ?? []).flatMap((f) =>
    f.items ? f.items.map((i) => ({ value: `${f.name}[0].${i.name}`, label: `${fieldName(f)} › ${fieldName(i)}` })) : [{ value: f.name, label: fieldName(f) }],
  )
}

/** 'Nombres + Apellido paterno' for a mapping's path(s). */
export function sourceLabel(type: DocumentTypeInfo | undefined, path: string | string[]): string {
  const options = fieldOptions(type)
  const one = (p: string) => options.find((o) => o.value === p.replace(/\[\d+\]/, '[0]'))?.label ?? p
  return (Array.isArray(path) ? path : [path]).map(one).join(' + ')
}
