// The words of the instructions page (VRT-93): the stage each instruction
// belongs to, and what the platform fills in where the text has {…}.

export const STAGES: { name: string; prompts: string[] }[] = [
  { name: 'Leer los documentos', prompts: ['quick_type', 'segment', 'classify', 'extract_agentic', 'extract_generic', 'read_table_region', 'read_figure_region'] },
  { name: 'Comparar y revisar', prompts: ['entity_judge', 'lens_summary', 'lens_playbook'] },
  { name: 'Configurar la plataforma', prompts: ['suggest_document_type', 'propose_type_from_example', 'draft_rule'] },
  { name: 'Conversar', prompts: ['assistant'] },
]

export const FILLED: Record<string, string> = {
  hint: 'las pistas del tipo de documento',
  regions: 'las regiones de texto detectadas en el documento',
  schema: 'los campos que hay que extraer',
  grounding: 'el significado de negocio de los campos, si está activado',
  types: 'los tipos de documento registrados',
  known_types: 'los tipos de documento registrados',
  attributes: 'los datos del catálogo de datos',
  roles: 'las personas del expediente (titular, cónyuge…)',
  area: 'el área (Riesgos o Legal)',
  instructions: 'el enfoque que definió el área',
  playbook: 'los puntos del playbook de Legal',
  self_check: 'la indicación de revisar el borrador con las reglas del documento antes de entregarlo, si está activada',
}

export const shortVersion = (version: string) => version.slice(0, 7)
