// The words of the connected systems page (VRT-97): how a system is doing,
// in a traffic light, and when things happened, as a person says it.
import type { ApiClientView } from '@/types/api'

const DAY = 86_400_000

export type SystemState = 'in_use' | 'idle' | 'never' | 'revoked'

export const STATE: Record<SystemState, { label: string; dot: string; hint: string }> = {
  in_use: { label: 'En uso', dot: 'bg-emerald-500', hint: 'Llamó a Veritium en los últimos 7 días.' },
  idle: { label: 'Sin uso reciente', dot: 'bg-amber-500', hint: 'Lleva más de 7 días sin llamar: ¿sigue en uso?' },
  never: { label: 'Aún no se conecta', dot: 'bg-amber-500', hint: 'Tiene credenciales pero todavía no ha llamado.' },
  revoked: { label: 'Sin acceso', dot: 'bg-muted-foreground/40', hint: 'Ya no puede llamar a Veritium.' },
}

export function stateOf(client: ApiClientView, now = Date.now()): SystemState {
  if (client.revoked_at) return 'revoked'
  if (!client.last_used_at) return 'never'
  return now - new Date(client.last_used_at).getTime() <= 7 * DAY ? 'in_use' : 'idle'
}

export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return 'nunca'
  const minutes = Math.round((now - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return 'hace un momento'
  if (minutes < 60) return `hace ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return hours === 1 ? 'hace 1 hora' : `hace ${hours} horas`
  const days = Math.round(hours / 24)
  if (days < 30) return days === 1 ? 'ayer' : `hace ${days} días`
  const months = Math.round(days / 30)
  return months === 1 ? 'hace 1 mes' : `hace ${months} meses`
}
