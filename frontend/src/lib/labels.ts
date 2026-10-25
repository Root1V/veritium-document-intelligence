// What a person reads instead of the system's codes (VRT-73): a document's
// status in business words, with a tone for its color, and each document
// type by the name the catalog gives it.
import { useCallback } from 'react'
import { useDocumentTypeCatalog } from '@/lib/queries'

export type Tone = 'ok' | 'warn' | 'bad' | 'busy' | 'neutral'

export const DOCUMENT_STATUS: Record<string, { label: string; tone: Tone }> = {
  uploaded: { label: 'Recibido', tone: 'busy' },
  processing: { label: 'Procesando', tone: 'busy' },
  parsing: { label: 'Leyendo', tone: 'busy' },
  classifying: { label: 'Identificando', tone: 'busy' },
  extracting: { label: 'Extrayendo datos', tone: 'busy' },
  extracted: { label: 'Datos extraídos', tone: 'busy' },
  validating: { label: 'Validando', tone: 'busy' },
  segmented: { label: 'Separado en varios', tone: 'neutral' },
  needs_review: { label: 'Por revisar', tone: 'warn' },
  completed: { label: 'Listo', tone: 'ok' },
  failed: { label: 'No se pudo leer', tone: 'bad' },
}

export function documentStatus(status: string): { label: string; tone: Tone } {
  return DOCUMENT_STATUS[status] ?? { label: status, tone: 'neutral' }
}

/** The catalog's name for a document type key ("payslip" → "Boleta de pago"). */
export function useTypeName(): (key: string | null | undefined) => string {
  const { data } = useDocumentTypeCatalog()
  return useCallback(
    (key) => {
      if (!key) return 'Sin clasificar'
      if (key === 'generic') return 'Otro documento'
      return data?.registered.find((t) => t.name === key)?.display_name ?? key
    },
    [data],
  )
}
