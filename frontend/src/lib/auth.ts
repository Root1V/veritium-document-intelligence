// Session storage + read/write helpers — holds the JWT, display name, the
// business unit and the role there returned at login. The role is re-checked server-side on every
// mutating request (see api/deps.require_role); what's stored here only
// drives which UI affordances are shown, never the actual authorization.

import type { BusinessUnit, Me, UserRole } from '@/types/api'

const TOKEN_KEY = 'idp_access_token'
const USER_NAME_KEY = 'idp_user_name'
const USER_ROLE_KEY = 'idp_user_role'
const UNIT_KEY = 'idp_unit'
const UNITS_KEY = 'idp_units'
// The last unit worked in survives signing out: the next sign-in starts there.
const LAST_UNIT_KEY = 'idp_last_unit'
// The identity provider's id_token, to end its session too on signing out (VRT-57).
const ID_TOKEN_KEY = 'idp_id_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getUserName(): string | null {
  return localStorage.getItem(USER_NAME_KEY)
}

export function getUserRole(): UserRole | null {
  return (localStorage.getItem(USER_ROLE_KEY) as UserRole | null) ?? null
}

/** The business unit everything on screen belongs to (VRT-57). */
export function getUnit(): string | null {
  return localStorage.getItem(UNIT_KEY)
}

export function getUnits(): BusinessUnit[] {
  try {
    return JSON.parse(localStorage.getItem(UNITS_KEY) ?? '[]') as BusinessUnit[]
  } catch {
    return []
  }
}

export function getLastUnit(): string | null {
  return localStorage.getItem(LAST_UNIT_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function setSession(token: string, me: Me): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_NAME_KEY, me.user_name)
  localStorage.setItem(USER_ROLE_KEY, me.role)
  localStorage.setItem(UNIT_KEY, me.tenant)
  localStorage.setItem(UNITS_KEY, JSON.stringify(me.tenants))
  localStorage.setItem(LAST_UNIT_KEY, me.tenant)
}

export function setIdToken(idToken: string): void {
  localStorage.setItem(ID_TOKEN_KEY, idToken)
}

export function clearSession(): void {
  for (const key of [TOKEN_KEY, USER_NAME_KEY, USER_ROLE_KEY, UNIT_KEY, UNITS_KEY, ID_TOKEN_KEY]) {
    localStorage.removeItem(key)
  }
}

/** Out of Veritium and out of the identity provider too — or the next
 * sign-in would resume the same person. Always through the provider, even
 * after a password sign-in: its session may still be open from an earlier
 * one. With the id_token it ends at once; without it, the provider asks
 * once; with no session there, it comes straight back to the login page. */
export function signOut(): void {
  const idToken = localStorage.getItem(ID_TOKEN_KEY)
  clearSession()
  window.location.assign(`/api/auth/oidc/logout${idToken ? `?id_token_hint=${encodeURIComponent(idToken)}` : ''}`)
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
