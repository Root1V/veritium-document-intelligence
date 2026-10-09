import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Upload, Files, ClipboardCheck, Sparkles, BookOpen, History, LogOut, FileStack, Users, ShieldCheck, ListChecks, Network, Workflow, FolderOpen, FlaskConical, Gauge } from 'lucide-react'
import { cn } from '@/lib/utils'
import { canExecute, clearSession, getUserName, getUserRole, isAdmin } from '@/lib/auth'
import { Badge } from '@/components/ui/badge'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Admin',
  operador: 'Operador',
  visor: 'Visor',
}

const NAV_ITEMS = [
  { to: '/', label: 'Inicio', icon: LayoutDashboard, end: true, requiresExecute: false },
  { to: '/upload', label: 'Subir documentos', icon: Upload, requiresExecute: true },
  { to: '/cases', label: 'Expedientes', icon: FolderOpen, requiresExecute: false },
  { to: '/documents', label: 'Documentos', icon: Files, requiresExecute: false },
  { to: '/review', label: 'Cola de revisión', icon: ClipboardCheck, requiresExecute: false },
  { to: '/type-suggestions', label: 'Sugerencias de tipo', icon: Sparkles, requiresExecute: false },
  { to: '/document-types', label: 'Plantillas', icon: BookOpen, requiresExecute: false },
  { to: '/profiles', label: 'Perfiles de proceso', icon: Workflow, requiresExecute: false },
  { to: '/semantic-catalog', label: 'Catálogo semántico', icon: Network, requiresExecute: false },
  { to: '/audit', label: 'Auditoría', icon: History, requiresExecute: false },
  { to: '/validation', label: 'Validación', icon: ShieldCheck, requiresExecute: false },
  { to: '/validation-rules', label: 'Reglas de validación', icon: ListChecks, requiresExecute: false },
  { to: '/evaluation', label: 'Evaluación', icon: FlaskConical, requiresExecute: false },
  { to: '/calibration', label: 'Confiabilidad', icon: Gauge, requiresExecute: false },
]

export function Sidebar() {
  const userName = getUserName()
  const role = getUserRole()
  const executeAllowed = canExecute()
  const navItems = executeAllowed ? NAV_ITEMS : NAV_ITEMS.filter((item) => !item.requiresExecute)

  return (
    <aside className="flex h-svh w-64 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2 px-5 py-5">
        <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <FileStack className="size-5" />
        </div>
        <div>
          <div className="text-sm font-semibold leading-tight">Veritium</div>
          <div className="text-xs text-muted-foreground leading-tight">Plataforma Documental</div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                  : 'text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              )
            }
          >
            <Icon className="size-4" />
            {label}
          </NavLink>
        ))}
        {isAdmin() && (
          <NavLink
            to="/users"
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                  : 'text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              )
            }
          >
            <Users className="size-4" />
            Usuarios
          </NavLink>
        )}
      </nav>

      <div className="border-t px-3 py-4">
        <div className="mb-2 flex items-center gap-2 px-2">
          <span className="text-sm font-medium">{userName ?? 'Usuario'}</span>
          {role && (
            <Badge variant="outline" className="text-[10px]">
              {ROLE_LABEL[role] ?? role}
            </Badge>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            clearSession()
            window.location.assign('/login')
          }}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        >
          <LogOut className="size-4" />
          Cerrar sesión
        </button>
      </div>
    </aside>
  )
}
