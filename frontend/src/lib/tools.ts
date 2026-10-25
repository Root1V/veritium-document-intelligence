// The words of the tools page (VRT-95): what each tool is for, grouped the
// way a person asks about them — what other systems can do, and what each of
// Veritium's own agents uses inside.
import type { ToolSpec } from '@/types/api'

export type ToolGroup = 'cases' | 'consult' | 'areas' | 'extraction' | 'investigation' | 'other'

export const GROUPS: { key: ToolGroup; name: string; hint: string; exposure: ToolSpec['exposure'] }[] = [
  { key: 'cases', name: 'Abrir y completar expedientes', hint: 'Un sistema envía documentos y Veritium los revisa.', exposure: 'mcp' },
  { key: 'consult', name: 'Consultar', hint: 'El estado, el resultado y la evidencia, sin cambiar nada.', exposure: 'mcp' },
  { key: 'areas', name: 'Riesgos y Legal', hint: 'Las lecturas que cada área hace de un expediente.', exposure: 'mcp' },
  { key: 'extraction', name: 'Agente que lee los documentos', hint: 'Lo que usa para sacar cada dato con su cita.', exposure: 'internal' },
  { key: 'investigation', name: 'Agente que investiga observaciones', hint: 'Lo que usa para encontrar por qué no cuadra un dato.', exposure: 'internal' },
  { key: 'other', name: 'Otras', hint: '', exposure: 'internal' },
]

const BY_NAME: Record<string, ToolGroup> = {
  submit_case: 'cases',
  add_documents: 'cases',
  request_documents_link: 'cases',
  quick_check_document: 'cases',
  list_processes: 'consult',
  get_case_status: 'consult',
  get_case_result: 'consult',
  find_cases: 'consult',
  cases_overview: 'consult',
  get_review_queue: 'consult',
  get_field_evidence: 'consult',
  list_lenses: 'areas',
  read_with_lens: 'areas',
}

export function groupOf(tool: ToolSpec): ToolGroup {
  if (BY_NAME[tool.name]) return BY_NAME[tool.name]
  if (tool.roles.includes('agente-extraccion')) return 'extraction'
  if (tool.roles.includes('agente-investigador')) return 'investigation'
  return tool.exposure === 'mcp' ? 'consult' : 'other'
}

// What a person reads; the description, written for the agents, goes folded.
export const SUMMARY: Record<string, string> = {
  read_text_region: 'Lee el texto ya reconocido de una zona del documento.',
  read_table_region: 'Mira una tabla del documento con IA para entender sus filas y columnas.',
  read_figure_region: 'Mira un gráfico o una figura del documento con IA.',
  check_draft: 'Revisa lo leído con las reglas propias del documento antes de entregarlo.',
  get_evidence: 'Muestra de dónde sale un dato y si los documentos coinciden.',
  read_document: 'Lee una parte o una página de un documento del expediente.',
  search_document: 'Busca un texto en un documento, aunque cambien tildes o mayúsculas.',
  read_region_image: 'Mira con IA una zona del documento cuando el texto reconocido no basta.',
  compare_names: 'Compara dos nombres de persona aunque cambie el orden, las tildes o falte un apellido.',
  find_employee: 'Busca a una persona en el maestro de empleados, por código o por nombre.',
  list_processes: 'Los procesos que Veritium sabe revisar y qué documentos pide cada uno.',
  submit_case: 'Abre un expediente con sus documentos y lo revisa; la decisión llega en minutos.',
  add_documents: 'Agrega documentos a un expediente abierto y lo vuelve a revisar.',
  request_documents_link: 'Crea un enlace para que el cliente suba sus documentos desde el teléfono.',
  quick_check_document: 'Antes de enviar un archivo, revisa en segundos si se puede leer y qué documento es.',
  get_case_status: 'En qué etapa va un expediente.',
  get_case_result: 'La decisión sobre un expediente, sus motivos y lo que falta.',
  find_cases: 'Busca expedientes por referencia, fecha de llegada o decisión.',
  cases_overview: 'Cuántos expedientes llegaron en un período y cómo van.',
  get_review_queue: 'Los datos que esperan que una persona los revise.',
  get_field_evidence: 'De dónde sale un dato del expediente y si los documentos coinciden.',
  list_lenses: 'Las lecturas que Riesgos y Legal pueden pedir de un expediente.',
  read_with_lens: 'Lee un expediente como lo pide Riesgos o Legal, citando cada documento.',
}

export const COST:Record<ToolSpec['cost'], { label: string; dot: string }> = {
  ninguno: { label: 'Sin costo', dot: 'bg-emerald-500' },
  lectura: { label: 'Consulta', dot: 'bg-emerald-500' },
  modelo: { label: 'Una llamada al modelo', dot: 'bg-amber-500' },
  procesamiento: { label: 'Procesa un expediente', dot: 'bg-red-500' },
}

export const ROLE: Record<string, string> = {
  visor: 'Visor',
  operador: 'Operador',
  admin: 'Admin',
  integracion: 'Sistemas conectados',
  especialista_ia: 'Especialista IA',
  'agente-extraccion': 'Agente de lectura',
  'agente-investigador': 'Agente investigador',
}
