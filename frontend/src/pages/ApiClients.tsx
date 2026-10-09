// Connected systems (VRT-65), for admins: each system that calls Veritium
// from its own back end gets its own credentials — shown once — that can
// be rotated or revoked without touching anyone else, and a call quota.
import { useState } from 'react'
import { Copy, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { errorDetail } from '@/lib/apiErrors'
import { useApiClientAction, useApiClients } from '@/lib/queries'
import type { ApiClientWithSecret } from '@/types/api'

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }) : '—')

function Secret({ client, onClose }: { client: ApiClientWithSecret; onClose: () => void }) {
  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast.success('Copiado.'))
  return (
    <div className="flex flex-col gap-2 rounded-md border border-amber-500/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
      <strong>Credenciales de «{client.name}»</strong>
      <span>Cópialas ahora y entrégalas al equipo del sistema por un canal seguro. El secreto no se volverá a mostrar.</span>
      {[
        ['client_id', client.client_id],
        ['client_secret', client.client_secret],
      ].map(([label, value]) => (
        <div key={label} className="flex items-center gap-2">
          <span className="w-28 shrink-0 text-xs text-muted-foreground">{label}</span>
          <Input readOnly value={value} onFocus={(e) => e.target.select()} className="font-mono text-xs" />
          <Button size="sm" variant="outline" onClick={() => copy(value)}>
            <Copy className="size-3.5" />
          </Button>
        </div>
      ))}
      <div>
        <Button size="sm" onClick={onClose}>
          Ya las guardé
        </Button>
      </div>
    </div>
  )
}

export function ApiClientsPage() {
  const { data: clients, isLoading } = useApiClients()
  const action = useApiClientAction()
  const [name, setName] = useState('')
  const [rateLimit, setRateLimit] = useState('')
  const [shown, setShown] = useState<ApiClientWithSecret | null>(null)
  const base = `${window.location.origin}/api`

  const run = (input: Parameters<typeof action.mutate>[0], done?: string) =>
    action.mutate(input, {
      onSuccess: (c) => {
        if ('client_secret' in c) setShown(c as ApiClientWithSecret)
        if (done) toast.success(done)
      },
      onError: (e) => toast.error(errorDetail(e)),
    })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Sistemas conectados</h1>
        <p className="text-muted-foreground">
          Los sistemas que llaman a Veritium desde su propio servidor. Cada uno tiene sus credenciales y su cuota de llamadas; puedes cambiarlas o
          cortarle el acceso sin afectar a los demás.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Conectar un sistema</CardTitle>
          <CardDescription>Podrá enviar y consultar expedientes, sesiones de carga y cargas masivas; nada de administración.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Nombre del sistema</span>
              <Input placeholder="p. ej. Core bancario" value={name} onChange={(e) => setName(e.target.value)} className="w-64" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Llamadas por minuto (opcional)</span>
              <Input
                type="number"
                min={1}
                placeholder="por defecto"
                value={rateLimit}
                onChange={(e) => setRateLimit(e.target.value)}
                className="w-40"
              />
            </label>
            <Button
              disabled={name.trim().length < 3 || action.isPending}
              onClick={() => {
                run({ kind: 'create', name: name.trim(), rateLimit: rateLimit ? Number(rateLimit) : undefined })
                setName('')
                setRateLimit('')
              }}
            >
              {action.isPending && <Loader2 className="size-4 animate-spin" />} Crear credenciales
            </Button>
          </div>
          {shown && <Secret client={shown} onClose={() => setShown(null)} />}
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">Cómo se conecta el sistema (para su equipo técnico)</summary>
            <div className="mt-2 flex flex-col gap-2">
              <span>
                1. Pide un token con sus credenciales (OAuth2 <em>client credentials</em>). Dura 15 minutos; al vencer, pide otro.
              </span>
              <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{`curl -X POST ${base}/auth/token \\
  -d grant_type=client_credentials \\
  -d client_id=$CLIENT_ID -d client_secret=$CLIENT_SECRET`}</pre>
              <span>2. Llama a la API con el token. Si supera su cuota recibe 429 y el header Retry-After con los segundos a esperar.</span>
              <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{`curl ${base}/v1/cases -H "Authorization: Bearer $TOKEN"`}</pre>
              <span>
                La referencia completa de la API está en <code>/docs</code> del servicio.
              </span>
            </div>
          </details>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sistemas</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          ) : !clients?.length ? (
            <span className="text-sm text-muted-foreground">Todavía no hay sistemas conectados.</span>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Sistema</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Cuota</TableHead>
                  <TableHead>Actividad</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {clients.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <div className="font-medium">{c.name}</div>
                      <code className="text-xs text-muted-foreground">{c.client_id}</code>
                    </TableCell>
                    <TableCell>
                      {c.revoked_at ? <Badge variant="destructive">Sin acceso</Badge> : <Badge variant="secondary">Activo</Badge>}
                    </TableCell>
                    <TableCell className="text-sm">{c.rate_limit_per_minute} / min</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      <div>Último uso: {when(c.last_used_at)}</div>
                      <div>Secreto desde: {when(c.secret_rotated_at)}</div>
                    </TableCell>
                    <TableCell>
                      {!c.revoked_at && (
                        <div className="flex flex-col items-start gap-1 xl:flex-row xl:gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={action.isPending}
                            onClick={() =>
                              confirm(`¿Cambiar el secreto de «${c.name}»? El actual deja de funcionar ahora mismo.`) &&
                              run({ kind: 'rotate', id: c.id })
                            }
                          >
                            Cambiar secreto
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={action.isPending}
                            onClick={() =>
                              confirm(`¿Quitar el acceso a «${c.name}»? No podrá volver a llamar a Veritium.`) &&
                              run({ kind: 'revoke', id: c.id }, 'Acceso retirado.')
                            }
                          >
                            Quitar acceso
                          </Button>
                        </div>
                      )}
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
