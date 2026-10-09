import { type FormEvent, useState } from 'react'
import { Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { useCreateUser, useUsers } from '@/lib/queries'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import type { UserRole } from '@/types/api'

const ROLE_LABEL: Record<UserRole, string> = {
  admin: 'Admin',
  operador: 'Operador',
  visor: 'Visor',
  integracion: 'Integración',
  especialista_ia: 'Especialista IA',
}

function CreateUserDialog() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<UserRole>('operador')
  const createUser = useCreateUser()

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    createUser.mutate(
      { name, email, password, role },
      {
        onSuccess: () => {
          toast.success('Usuario creado.')
          setOpen(false)
          setName('')
          setEmail('')
          setPassword('')
          setRole('operador')
        },
        onError: () => toast.error('No se pudo crear el usuario.'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="size-4" />
          Nuevo usuario
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuevo usuario</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">Nombre</Label>
            <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">Correo</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Contraseña</Label>
            <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Rol</Label>
            <Select value={role} onValueChange={(v) => setRole(v as UserRole)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="visor">Visor — solo lectura</SelectItem>
                <SelectItem value="operador">Operador — puede ejecutar acciones</SelectItem>
                <SelectItem value="especialista_ia">Especialista IA — edita las instrucciones al modelo</SelectItem>
                <SelectItem value="admin">Admin — todo, incluida gestión de usuarios</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button type="submit" disabled={createUser.isPending} className="self-start">
            {createUser.isPending && <Loader2 className="size-4 animate-spin" />}
            Crear usuario
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function UsersPage() {
  const { data: users, isLoading } = useUsers()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Usuarios</h1>
          <p className="text-muted-foreground">Gestiona quién puede acceder a la plataforma y con qué rol.</p>
        </div>
        <CreateUserDialog />
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nombre</TableHead>
                <TableHead>Correo</TableHead>
                <TableHead>Rol</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(users ?? []).map((user) => (
                <TableRow key={user.id}>
                  <TableCell>{user.name}</TableCell>
                  <TableCell className="text-muted-foreground">{user.email}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-[10px]">
                      {ROLE_LABEL[user.role]}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
