// The words of the rules page (VRT-90): what a rule compares against, and
// how serious it is when it fails.
import type { RuleCelCategory } from '@/types/api'

/** The groups of the page, by what a rule compares the data against. */
export const GROUPS: { key: string; name: string; hint: string; categories: string[] }[] = [
  { key: 'self', name: 'Dentro del documento', hint: 'Que los datos de cada documento estén completos y cuadren entre sí.', categories: ['self', 'conditional'] },
  { key: 'cross', name: 'Entre documentos', hint: 'Que un mismo dato coincida en todos los documentos del expediente.', categories: ['cross_document', 'semantic'] },
  { key: 'request', name: 'Contra la solicitud', hint: 'Que los documentos digan lo mismo que se indicó al enviar la solicitud.', categories: ['request_input'] },
  { key: 'reference', name: 'Contra datos de referencia', hint: 'Que lo leído exista en los maestros de la entidad (empleados, convenios…).', categories: ['reference_data'] },
  { key: 'external', name: 'Contra sistemas externos', hint: 'Consultas a sistemas de otras entidades.', categories: ['external_system'] },
]

export const groupOf = (category: string) => GROUPS.find((g) => g.categories.includes(category)) ?? GROUPS[0]

/** What a new rule may compare against, as the person would say it. */
export const COMPARES: { value: RuleCelCategory; label: string; hint: string }[] = [
  { value: 'self', label: 'Con el propio documento', hint: 'p. ej. un mínimo, un formato, que el neto sea bruto menos descuentos' },
  { value: 'request_input', label: 'Con lo indicado en la solicitud', hint: 'p. ej. que el monto sea el que se pidió' },
  { value: 'reference_data', label: 'Con datos de referencia', hint: 'p. ej. que el código exista en el maestro de empleados' },
]

export const SEVERITY: Record<string, { label: string; dot: string }> = {
  error: { label: 'Grave', dot: 'bg-red-500' },
  warning: { label: 'Advertencia', dot: 'bg-amber-500' },
  info: { label: 'Informativa', dot: 'bg-sky-500' },
}
