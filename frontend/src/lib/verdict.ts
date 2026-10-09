import type { VerdictDecision } from '@/types/api'

export const VERDICT_LABEL: Record<VerdictDecision, string> = {
  continue: 'Continuar',
  human_review: 'Revisión humana',
  return_to_client: 'Devolver al cliente',
}

export const VERDICT_VARIANT: Record<VerdictDecision, 'secondary' | 'outline' | 'destructive'> = {
  continue: 'secondary',
  human_review: 'outline',
  return_to_client: 'destructive',
}
