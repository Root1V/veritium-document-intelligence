import type { EvalRate, EvalRunSummary } from '@/types/api'

/** "92% (23/25)", or "—" when nothing was evaluated. */
export function percent(rate: EvalRate | null | undefined): string {
  if (!rate || rate.accuracy === null) return '—'
  return `${Math.round(rate.accuracy * 100)}% (${rate.correct}/${rate.evaluated})`
}

export function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

// What each versioned prompt does, in the words of the business (VRT-46).
const PROMPT_LABEL: Record<string, string> = {
  classify: 'la clasificación de documentos',
  segment: 'la separación de documentos',
  extract_agentic: 'la extracción de datos',
  extract_generic: 'la extracción de documentos sin tipo',
  entity_judge: 'la comparación de nombres',
  draft_rule: 'la redacción de reglas',
  suggest_document_type: 'la sugerencia de tipos nuevos',
  propose_type_from_example: 'el tipo desde un ejemplo',
  read_table_region: 'la lectura de tablas',
  read_figure_region: 'la lectura de figuras',
  lens_summary: 'el resumen para Riesgos',
  lens_playbook: 'la revisión para Legal',
}

/** What differs between two runs' configuration, in plain words. */
export function configChanges(before: EvalRunSummary['provenance'], after: EvalRunSummary['provenance']): string[] {
  if (!before || !after) return []
  const out: string[] = []
  for (const [role, model] of Object.entries(after.models ?? {})) {
    const was = before.models?.[role]
    if (was && was !== model) out.push(`Modelo de ${role === 'vision' ? 'visión' : 'razonamiento'}: ${was} → ${model}`)
  }
  for (const [name, version] of Object.entries(after.prompts ?? {})) {
    const was = before.prompts?.[name]
    if (was && was !== version) out.push(`Cambiaron las instrucciones de ${PROMPT_LABEL[name] ?? name}`)
  }
  for (const [type, version] of Object.entries(after.document_types ?? {})) {
    const was = before.document_types?.[type]
    if (was && was !== version) out.push(`Plantilla «${type}»: versión ${was} → ${version}`)
  }
  if (Boolean(before.semantic_grounding) !== Boolean(after.semantic_grounding))
    out.push(after.semantic_grounding ? 'Se agregó el significado de negocio de cada campo' : 'Se quitó el significado de negocio de cada campo')
  if (before.self_check !== undefined && after.self_check !== undefined && before.self_check !== after.self_check)
    out.push(after.self_check ? 'Se activó la autovalidación del borrador' : 'Se desactivó la autovalidación del borrador')
  return out
}
