// The words of the document type pages (VRT-88): a field by its name, its
// format and what it means in the data catalog.
import { humanizeFieldName } from '@/lib/extraction'
import type { DocumentTypeFieldInfo, FieldSpecType, SemanticCatalog } from '@/types/api'

export const fieldName = (f: { name: string; label?: string | null }) => f.label || humanizeFieldName(f.name)

export const FORMAT: Record<FieldSpecType, string> = {
  str: 'Texto',
  int: 'Número entero',
  float: 'Número o monto',
  bool: 'Sí / No',
  enum: 'Una de varias opciones',
  list: 'Tabla',
}

// The options some built-in types read, as values in English.
const OPTION: Record<string, string> = { earning: 'ingreso', deduction: 'descuento' }

/** The catalog answers with 'str', 'list[Item]' or 'A | B' for the options. */
export function formatOf(field: DocumentTypeFieldInfo): string {
  if (field.field_type.startsWith('list')) return FORMAT.list
  if (field.field_type.includes(' | ')) return `Opciones: ${field.field_type.split(' | ').map((o) => OPTION[o] ?? o).join(', ')}`
  return FORMAT[field.field_type as FieldSpecType] ?? field.field_type
}

/** What a field means in the published data catalog: 'DNI · titular'. */
export function meaningOf(catalog: SemanticCatalog | undefined, typeKey: string, path: string): string | null {
  if (!catalog) return null
  const normalized = (p: string) => p.replace(/\[\d*\]/g, '[]')
  const mapping = catalog.mappings.find(
    (m) => m.document_type === typeKey && (Array.isArray(m.field_path) ? m.field_path : [m.field_path]).some((p) => normalized(p) === path),
  )
  if (!mapping) return null
  const attribute = catalog.attributes.find((a) => a.key === mapping.attribute)?.name ?? mapping.attribute
  const role = catalog.roles.find((r) => r.key === mapping.role)?.name ?? mapping.role
  return `${attribute} · ${role.toLowerCase()}`
}

/** Every field and table column, with the path the catalog and the labels use. */
export function flatten(fields: DocumentTypeFieldInfo[]): { path: string; field: DocumentTypeFieldInfo; depth: 0 | 1 }[] {
  return fields.flatMap((f) => [
    { path: f.name, field: f, depth: 0 as const },
    ...(f.items ?? []).map((i) => ({ path: `${f.name}[].${i.name}`, field: i, depth: 1 as const })),
  ])
}
