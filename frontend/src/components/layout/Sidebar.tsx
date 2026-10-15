import { NavLink } from 'react-router-dom'
import { toast } from 'sonner'
import { LayoutDashboard, Upload, Files, ClipboardCheck, Sparkles, BookOpen, History, LogOut, FileStack, Users, ShieldCheck, ListChecks, Network, Workflow, FolderOpen, FolderArchive, FlaskConical, Gauge, SplitSquareHorizontal, Scale, MessageSquareText, KeyRound, Wrench, Bot, Building2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { canExecute, getUnit, getUnits, getUserName, getUserRole, isAdmin, setSession, signOut } from '@/lib/auth'
import { useSwitchUnit } from '@/lib/queries'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Admin',
  operador: 'Operador',
  visor: 'Visor',
  integracion: 'Integración',
  especialista_ia: 'Especialista IA',
}

const NAV_ITEMS = [
  { to: '/', label: 'Inicio', icon: LayoutDashboard, end: true, requiresExecute: false },
  { to: '/upload', label: 'Subir documentos', icon: Upload, requiresExecute: true },
  { to: '/cases', label: 'Expedientes', icon: FolderOpen, requiresExecute: false },
  { to: '/asistente', label: 'Asistente', icon: Bot, requiresExecute: false },
  { to: '/bulk', label: 'Cargas masivas', icon: FolderArchive, requiresExecute: false },
  { to: '/documents', label: 'Documentos', icon: Files, requiresExecute: false },
  { to: '/review', label: 'Cola de revisión', icon: ClipboardCheck, requiresExecute: false },
  { to: '/type-suggestions', label: 'Sugerencias de tipo', icon: Sparkles, requiresExecute: false },
  { to: '/document-types', label: 'Plantillas', icon: BookOpen, requiresExecute: false },
  { to: '/profiles', label: 'Perfiles de proceso', icon: Workflow, requiresExecute: false },
  { to: '/semantic-catalog', label: 'Catálogo semántico', icon: Network, requiresExecute: false },
  { to: '/audit', label: 'Auditoría', icon: History, requiresExecute: false },
  { to: '/validation', label: 'Validación', icon: ShieldCheck, requiresExecute: false },
  { to: '/validation-rules', label: 'Reglas de validación', icon: ListChecks, requiresExecute: false },
  { to: '/lenses', label: 'Riesgos y Legal', icon: Scale, requiresExecute: false },
  { to: '/simulations', label: 'Probar cambios', icon: SplitSquareHorizontal, requiresExecute: false },
  { to: '/evaluation', label: 'Evaluación', icon: FlaskConical, requiresExecute: false },
  { to: '/calibration', label: 'Confiabilidad', icon: Gauge, requiresExecute: false },
  { to: '/prompts', label: 'Instrucciones al modelo', icon: MessageSquareText, requiresExecute: false },
  { to: '/tools', label: 'Catálogo de tools', icon: Wrench, requiresExecute: false },
]

/** The business unit everything on screen belongs to; someone in several picks one (VRT-57). */
function UnitPicker() {
  const units = getUnits()
  const current = getUnit()
  const switchUnit = useSwitchUnit()
  if (units.length === 0) return null
  if (units.length === 1) {
    return (
      <div className="mx-3 mb-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm">
        <Building2 className="size-4 text-muted-foreground" />
        <span className="truncate">{units[0].name}</span>
      </div>
    )
  }
  return (
    <div className="mx-3 mb-3">
      <Select
        value={current ?? undefined}
        disabled={switchUnit.isPending}
        onValueChange={(tenant) =>
          switchUnit.mutate(tenant, {
            onSuccess: (data) => {
              setSession(data.access_token, data)
              window.location.assign('/') // nothing of the previous unit stays on screen
            },
            onError: () => toast.error('No se pudo cambiar de unidad.'),
          })
        }
      >
        <SelectTrigger className="w-full" aria-label="Unidad de negocio">
          <Building2 className="size-4 text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {units.map((u) => (
            <SelectItem key={u.key} value={u.key}>
              {u.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

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

      <UnitPicker />

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
        {isAdmin() && (
          <NavLink
            to="/unidades"
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                  : 'text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              )
            }
          >
            <Building2 className="size-4" />
            Unidades de negocio
          </NavLink>
        )}
        {isAdmin() && (
          <NavLink
            to="/sistemas"
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                  : 'text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              )
            }
          >
            <KeyRound className="size-4" />
            Sistemas conectados
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
          onClick={signOut}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        >
          <LogOut className="size-4" />
          Cerrar sesión
        </button>
      </div>
    </aside>
  )
}
