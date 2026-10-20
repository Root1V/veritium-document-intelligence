// Business units (VRT-57), for the platform team (VRT-71): register a unit — blank, or with the example processes — and rename it. Who
// works in each one, and with which role, comes from the corporate identity
// provider's groups — the page lists the ones to create there.
import { useState } from 'react'
import { Copy, Loader2, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { errorDetail } from '@/lib/apiErrors'
import { useBusinessUnitAction, useBusinessUnits } from '@/lib/queries'

const ROLE_LABEL: Record<string, string> = { admin: 'Admin', operador: 'Operador', visor: 'Visor', especialista_ia: 'Especialista IA' }

/** "Banca Corporativa" → "banca-corporativa": what goes in the groups. */
const toKey = (name: string) =>
  name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)

export function BusinessUnitsPage() {
  const { data: units, isLoading } = useBusinessUnits()
  const action = useBusinessUnitAction()
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  const [keyTouched, setKeyTouched] = useState(false)
  const [examples, setExamples] = useState(false)
  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast.success('Copiado.'))
  const shownKey = keyTouched ? key : toKey(name)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Unidades de negocio</h1>
        <p className="text-muted-foreground">
          Cada unidad ve solo sus expedientes, procesos, sistemas conectados y revisiones. Quién trabaja en cada una, y con qué rol, se define
          en la cuenta corporativa: agrega a las personas a los grupos de la unidad.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Nueva unidad</CardTitle>
          <CardDescription>
            Empieza en blanco: solo el proceso interno «Ad-hoc», que usa la carga directa. Nadie entra hasta que tenga un grupo de la unidad.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Nombre</span>
            <Input placeholder="p. ej. Banca Corporativa" value={name} onChange={(e) => setName(e.target.value)} className="w-64" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Identificador (va en los grupos; no cambia)</span>
            <Input
              placeholder="banca-corporativa"
              value={shownKey}
              onChange={(e) => {
                setKeyTouched(true)
                setKey(e.target.value)
              }}
              className="w-56 font-mono"
            />
          </label>
          <label className="flex items-center gap-2 self-center text-sm">
            <input type="checkbox" checked={examples} onChange={(e) => setExamples(e.target.checked)} />
            Incluir procesos de ejemplo
          </label>
          <Button
            disabled={name.trim().length < 2 || !shownKey || action.isPending}
            onClick={() =>
              action.mutate(
                { kind: 'create', key: shownKey, name: name.trim(), examples },
                {
                  onSuccess: (u) => {
                    toast.success(`Unidad «${u.name}» creada. Ahora crea sus grupos en la cuenta corporativa.`)
                    setName('')
                    setKey('')
                    setKeyTouched(false)
                    setExamples(false)
                  },
                  onError: (e) => toast.error(errorDetail(e)),
                },
              )
            }
          >
            {action.isPending && <Loader2 className="size-4 animate-spin" />} Crear unidad
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Unidades</CardTitle>
          <CardDescription>
            Para dar acceso, agrega a la persona al grupo de la unidad con el rol que corresponde en el proveedor de identidad (en desarrollo,
            Keycloak). El cambio se aplica en su siguiente ingreso.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Unidad</TableHead>
                  <TableHead>Personas</TableHead>
                  <TableHead>Grupos en la cuenta corporativa</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(units ?? []).map((u) => (
                  <TableRow key={u.key}>
                    <TableCell>
                      <div className="font-medium">{u.name}</div>
                      <code className="text-xs text-muted-foreground">{u.key}</code>
                    </TableCell>
                    <TableCell className="text-sm">{u.people}</TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        {u.groups.map((g) => (
                          <div key={g} className="flex items-center gap-2 text-xs">
                            <span className="w-24 text-muted-foreground">{ROLE_LABEL[g.split(':').pop() ?? ''] ?? ''}</span>
                            <code>{g}</code>
                            <button type="button" aria-label={`Copiar ${g}`} onClick={() => copy(g)} className="text-muted-foreground hover:text-foreground">
                              <Copy className="size-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={action.isPending}
                        onClick={() => {
                          const next = prompt(`Nuevo nombre para «${u.name}»`, u.name)?.trim()
                          if (next && next !== u.name)
                            action.mutate({ kind: 'rename', key: u.key, name: next }, { onSuccess: () => toast.success('Nombre actualizado.'), onError: (e) => toast.error(errorDetail(e)) })
                        }}
                      >
                        <Pencil className="size-3.5" /> Renombrar
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
