// The words of the process editor (VRT-87): requirement identifiers, when a
// requirement applies, and a rule's failure said as an outcome.
import type { ChecklistItem, RuleBinding } from '@/types/api'

/** An identifier from what a person wrote: "Boleta de pago" → "boleta_de_pago". */
export function slug(text: string, sep = '_'): string {
  return text
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, sep)
    .replace(new RegExp(`^\\${sep}+|\\${sep}+$`, 'g'), '')
    .slice(0, 60)
}

export type When = 'always' | 'optional' | 'condition'
export const whenOf = (item: ChecklistItem): When => (item.required_when_cel != null ? 'condition' : item.required ? 'always' : 'optional')

export type Outcome = 'inform' | 'warn' | 'error' | 'review' | 'return'

export const OUTCOME: Record<Outcome, { label: string; binding: Omit<RuleBinding, 'rule_id'>; tone: string }> = {
  inform: { label: 'Solo informar', binding: { severity: 'info', blocking: false, on_fail: 'human_review' }, tone: 'text-muted-foreground' },
  warn: { label: 'Advertir', binding: { severity: 'warning', blocking: false, on_fail: 'human_review' }, tone: 'text-muted-foreground' },
  error: { label: 'Marcar como error', binding: { severity: 'error', blocking: false, on_fail: 'human_review' }, tone: 'text-muted-foreground' },
  review: { label: 'Enviar a revisión humana', binding: { severity: 'error', blocking: true, on_fail: 'human_review' }, tone: 'text-amber-700 dark:text-amber-400' },
  return: { label: 'Devolver al cliente', binding: { severity: 'error', blocking: true, on_fail: 'return_to_client' }, tone: 'text-red-700 dark:text-red-400' },
}

export const outcomeOf = (b: RuleBinding): Outcome =>
  b.blocking ? (b.on_fail === 'return_to_client' ? 'return' : 'review') : b.severity === 'info' ? 'inform' : b.severity === 'warning' ? 'warn' : 'error'

