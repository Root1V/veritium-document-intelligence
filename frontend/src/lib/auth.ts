// Session storage + read/write helpers — holds the JWT, display name and
// role returned at login. The role is re-checked server-side on every
// mutating request (see api/deps.require_role); what's stored here only
// drives which UI affordances are shown, never the actual authorization.

import type { UserRole } from '@/types/api'

const TOKEN_KEY = 'idp_access_token'
const USER_NAME_KEY = 'idp_user_name'
const USER_ROLE_KEY = 'idp_user_role'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getUserName(): string | null {
  return localStorage.getItem(USER_NAME_KEY)
}

export function getUserRole(): UserRole | null {
  return (localStorage.getItem(USER_ROLE_KEY) as UserRole | null) ?? null
}

export function setSession(token: string, userName: string, role: UserRole): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_NAME_KEY, userName)
  localStorage.setItem(USER_ROLE_KEY, role)
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_NAME_KEY)
  localStorage.removeItem(USER_ROLE_KEY)
}

export function isAuthenticated(): boolean {
  return getToken() !== null
}

/** "operador" and "admin" can execute actions (upload, correct, resolve
 * suggestions, manage users where applicable); "visor" is read-only. */
export function canExecute(): boolean {
  const role = getUserRole()
  return role === 'operador' || role === 'admin'
}

export function isAdmin(): boolean {
  return getUserRole() === 'admin'
}

/** Edits the instructions to the model and tries them in evaluations (VRT-63). */
export function isAISpecialist(): boolean {
  return getUserRole() === 'especialista_ia'
}
