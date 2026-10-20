import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { getUserRole, isPlatformAdmin } from '@/lib/auth'
import type { UserRole } from '@/types/api'

/** Route-level gate for a specific role set, layered under ProtectedRoute
 * (which only checks "logged in or not"). A denied visitor is bounced to
 * the dashboard rather than shown an empty/broken page — the sidebar
 * already hides these routes for the wrong role, this only covers direct
 * navigation. The server independently enforces the same roles on every
 * mutating endpoint (see api/deps.require_role) — this check is UX, not
 * the security boundary. */
export function RequireRole({ roles, children }: { roles: UserRole[]; children: ReactNode }) {
  const role = getUserRole()
  if (!role || !roles.includes(role)) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}

/** The same gate for what only the platform team does (VRT-71). */
export function RequirePlatform({ children }: { children: ReactNode }) {
  return isPlatformAdmin() ? <>{children}</> : <Navigate to="/" replace />
}
