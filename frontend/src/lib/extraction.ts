// Shared helpers for walking a document's `extraction` payload generically
// — one renderer for any of the 12+ document-type schemas (4-30 fields
// each, several with nested line-item lists) instead of one layout per
// type. New types (once a type-suggestion is coded) render automatically.
import type { Extracted } from '@/types/api'

export function isExtractedEnvelope(value: unknown): value is Extracted<unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    'value' in value &&
    'confidence' in value &&
    'page' in value &&
    'bbox' in value
  )
}

export function humanizeFieldName(name: string): string {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return value.toLocaleString('es-PE', { maximumFractionDigits: 2 })
  return String(value)
}

export type ConfidenceLevel = 'high' | 'medium' | 'low'

export function confidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.85) return 'high'
  if (confidence >= 0.6) return 'medium'
  return 'low'
}

/** Splits a document's extraction payload into top-level scalar fields
 * (rendered as `ExtractionField`s) and list-of-line-item fields (rendered
 * as `ExtractionTable`s) — covers every schema without per-type code. */
// What the platform notes about the document, not data read from it: the fields
// that cannot be read (VRT-112, shown in review) and the machine-readable lines
// it checked (VRT-116, shown in validation).
const NOT_DATA = new Set(['unreadable_fields', 'machine_readable_zones'])

export function splitExtractionPayload(payload: Record<string, unknown>): {
  fields: [string, Extracted<unknown>][]
  tables: [string, Record<string, unknown>[]][]
} {
  const fields: [string, Extracted<unknown>][] = []
  const tables: [string, Record<string, unknown>[]][] = []

  for (const [key, value] of Object.entries(payload)) {
    if (isExtractedEnvelope(value)) {
      fields.push([key, value])
    } else if (Array.isArray(value) && !NOT_DATA.has(key)) {
      tables.push([key, value as Record<string, unknown>[]])
    }
  }
  return { fields, tables }
}

/** Flattens every `Extracted[T]` leaf in a payload (top-level fields AND
 * table cells) into a single key -> envelope map, keyed the same way
 * `ExtractionField`/`ExtractionTable` identify a field — lets the page
 * that owns selection state look up "what's the bbox for this key" and
 * "what's on the current page" without knowing the schema shape. */
export function flattenExtraction(payload: Record<string, unknown>): Record<string, Extracted<unknown>> {
  const { fields, tables } = splitExtractionPayload(payload)
  const flat: Record<string, Extracted<unknown>> = {}
  for (const [key, envelope] of fields) flat[key] = envelope
  for (const [tableName, rows] of tables) {
    rows.forEach((row, rowIndex) => {
      for (const [col, cellValue] of Object.entries(row)) {
        if (isExtractedEnvelope(cellValue)) flat[`${tableName}[${rowIndex}].${col}`] = cellValue
      }
    })
  }
  return flat
}
