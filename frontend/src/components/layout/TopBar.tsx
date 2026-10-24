// What is always at hand (VRT-73): search across every document (VRT-59),
// open a new case, the business unit and the person's own menu.
import { type FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Building2, ChevronDown, LogOut, Plus, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { canExecute, getUnit, getUnits, getUserName, getUserRole, setSession, signOut } from '@/lib/auth'
import { useSwitchUnit } from '@/lib/queries'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrador',
  operador: 'Operador',
  visor: 'Consulta',
  integracion: 'Integración',
  especialista_ia: 'Especialista IA',
}

/** The business unit everything on screen belongs to; someone in several picks one (VRT-57). */
function UnitPicker() {
  const units = getUnits()
  const current = getUnit()
  const switchUnit = useSwitchUnit()
  if (units.length === 0) return null
  if (units.length === 1) {
    return (
      <span className="hidden items-center gap-2 text-sm text-muted-foreground md:flex">
        <Building2 className="size-4" />
        {units[0].name}
      </span>
    )
  }
  return (
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
      <SelectTrigger className="w-48" aria-label="Unidad de negocio">
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
  )
}

function UserMenu() {
  const name = getUserName() ?? 'Usuario'
  const role = getUserRole()
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-muted" aria-label="Tu cuenta">
          <span className="flex size-8 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{initials}</span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="flex flex-col">
          <span>{name}</span>
          {role && <span className="text-xs font-normal text-muted-foreground">{ROLE_LABEL[role] ?? role}</span>}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={signOut}>
          <LogOut className="size-4" /> Cerrar sesión
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function TopBar() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  function search(e: FormEvent) {
    e.preventDefault()
    const q = query.trim()
    if (q) navigate(`/documents?q=${encodeURIComponent(q)}`)
  }

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/95 px-6 backdrop-blur">
      <form onSubmit={search} className="relative w-full max-w-md" role="search">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar por DNI, nombre o de qué trata el documento"
          aria-label="Buscar documentos"
          className="pl-9"
        />
      </form>
      <div className="ml-auto flex items-center gap-3">
        <UnitPicker />
        {canExecute() && (
          <Button onClick={() => navigate('/upload')}>
            <Plus className="size-4" /> Nuevo expediente
          </Button>
        )}
        <UserMenu />
      </div>
    </header>
  )
}
