// Adding someone to the unit, or changing their access (VRT-96): the role
// chosen from what each one can do, and taking them out of the unit at the
// bottom. Whoever signs in with a corporate account is only shown here.
import { useState } from 'react'
import { isAxiosError } from 'axios'
import { Building2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useDeleteAction } from '@/components/DeleteButton'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { ROLES, initials } from '@/lib/people'
import { useChangeUserRole, useCreateUser } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { AppUser, UserRole } from '@/types/api'

function RolePicker({ value, onChange, choices, disabled }: { value: UserRole; onChange: (role: UserRole) => void; choices: UserRole[]; disabled?: boolean }) {
  return (
    <div className="flex flex-col gap-2">
      {ROLES.filter((r) => choices.includes(r.key)).map((r) => {
        const chosen = r.key === value
        return (
          <button
            key={r.key}
            type="button"
            disabled={disabled}
            onClick={() => onChange(r.key)}
            className={cn('flex items-start gap-3 rounded-lg border p-3 text-left transition', chosen ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:border-primary/40', disabled && 'cursor-default opacity-70')}
          >
            <span className={cn('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border', chosen && 'border-primary bg-primary')}>
              {chosen && <span className="size-1.5 rounded-full bg-primary-foreground" />}
            </span>
            <span className="flex flex-col">
              <span className="text-sm font-medium">{r.name}</span>
              <span className="text-xs text-muted-foreground">{r.can}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

function createError(e: unknown) {
  if (isAxiosError(e) && e.response?.status === 409) return 'Esa persona ya está en esta unidad.'
  if (isAxiosError(e) && e.response?.status === 400 && String(e.response.data?.detail).includes('password')) return 'Es una persona nueva: ponle una contraseña inicial.'
  return errorDetail(e)
}

export function PersonDialog({ person, onClose }: { person: AppUser | null; onClose: () => void }) {
  const create = useCreateUser()
  const change = useChangeUserRole()
  const remove = useDeleteAction({
    path: `/users/${person?.id}`,
    question: `¿Quitar a ${person?.name} de esta unidad? Deja de tener acceso aquí; lo que hizo sigue registrado a su nombre.`,
    onDone: onClose,
  })
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<UserRole>(person?.role ?? 'operador')
  const corporate = person?.managed_by === 'idp'
  const choices: UserRole[] = ['admin', 'operador', 'especialista_ia', 'visor', ...(person?.role === 'integracion' ? (['integracion'] as const) : [])]

  const problem = person
    ? role === person.role
      ? 'Elige el nuevo rol.'
      : null
    : !name.trim()
      ? 'Falta el nombre.'
      : !/^\S+@\S+\.\S+$/.test(email.trim())
        ? 'Falta un correo válido.'
        : null

  const save = () =>
    person
      ? change.mutate(
          { id: person.id, role },
          {
            onSuccess: () => {
              toast.success(`${person.name} ahora es ${ROLES.find((r) => r.key === role)?.name}.`)
              onClose()
            },
            onError: (e) => toast.error(errorDetail(e)),
          },
        )
      : create.mutate(
          { name: name.trim(), email: email.trim(), password: password || undefined, role },
          {
            onSuccess: (u) => {
              toast.success(`${u.name} ya puede entrar a la unidad.`)
              onClose()
            },
            onError: (e) => toast.error(createError(e)),
          },
        )
  const pending = create.isPending || change.isPending

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="border-b px-6 py-4">
          {person ? (
            <div className="flex items-center gap-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{initials(person.name)}</span>
              <div className="flex min-w-0 flex-col text-left">
                <DialogTitle>{person.name}</DialogTitle>
                <DialogDescription className="truncate">{person.email}</DialogDescription>
              </div>
            </div>
          ) : (
            <>
              <DialogTitle>Agregar una persona</DialogTitle>
              <DialogDescription>Entra a esta unidad con su correo y el rol que elijas.</DialogDescription>
            </>
          )}
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          {!person && (
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 sm:col-span-2">
                <span className="text-sm font-medium">Correo</span>
                <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="nombre@empresa.com" autoFocus />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Nombre</span>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nombre y apellido" />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Contraseña inicial</span>
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
              </label>
              <p className="text-xs text-muted-foreground sm:col-span-2">Si ya trabaja en otra unidad, deja la contraseña vacía: entrará con la que ya tiene.</p>
            </div>
          )}

          {corporate && (
            <p className="flex items-start gap-2 rounded-lg bg-muted px-3 py-2.5 text-sm text-muted-foreground">
              <Building2 className="mt-0.5 size-4 shrink-0" />
              Entra con su cuenta corporativa: su rol se cambia en su grupo del proveedor de identidad, no aquí.
            </p>
          )}

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">{person ? 'Rol en esta unidad' : 'Qué podrá hacer'}</span>
            <RolePicker value={role} onChange={setRole} choices={choices} disabled={corporate} />
          </div>
        </div>

        <DialogFooter className="flex-row items-center gap-2 border-t px-6 py-4 sm:justify-between">
          {person && !corporate ? (
            <Button variant="ghost" className="text-destructive" disabled={remove.pending} onClick={remove.run}>
              Quitar de la unidad
            </Button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={onClose}>
              {corporate ? 'Cerrar' : 'Cancelar'}
            </Button>
            {!corporate && (
              <Button disabled={!!problem || pending} onClick={save} title={problem ?? undefined}>
                {pending && <Loader2 className="size-4 animate-spin" />} {person ? 'Guardar' : 'Agregar'}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
