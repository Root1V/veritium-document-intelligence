// The words of the people page (VRT-96): what each role can do in a unit,
// from the most to the least it allows.
import type { UserRole } from '@/types/api'

export const ROLES: { key: UserRole; name: string; can: string }[] = [
  { key: 'admin', name: 'Admin', can: 'Todo, incluido quién entra a la unidad y con qué rol.' },
  { key: 'operador', name: 'Operador', can: 'Carga expedientes, revisa y corrige datos.' },
  { key: 'especialista_ia', name: 'Especialista IA', can: 'Ajusta y prueba las instrucciones al modelo; lo demás, solo lo consulta.' },
  { key: 'visor', name: 'Visor', can: 'Solo consulta: ve expedientes y reportes, sin cambiar nada.' },
  { key: 'integracion', name: 'Integración', can: 'Cuenta de un sistema que envía expedientes por la API.' },
]

export const roleName = (role: UserRole) => ROLES.find((r) => r.key === role)?.name ?? role

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('')
