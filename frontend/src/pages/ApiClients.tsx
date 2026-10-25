// Connected systems (VRT-65, VRT-97), for admins: each system that calls
// Veritium from its own back end gets its own credentials — shown once — that
// can be rotated or revoked without touching anyone else, and a call quota.
// Each system shows how it is doing in a traffic light; the ones without
// access and the guide for their technical team stay folded.
import { useState } from 'react'
import { Copy, KeyRound, Loader2, Plug, Plus, RefreshCw, ShieldOff } from 'lucide-react'
import { toast } from 'sonner'
import { CredentialsDialog } from '@/components/systems/CredentialsDialog'
import { Button } from '@/components/ui/button'
import { errorDetail } from '@/lib/apiErrors'
import { STATE, ago, stateOf, type SystemState } from '@/lib/apiClients'
import { useApiClientAction, useApiClients } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ApiClientView, ApiClientWithSecret } from '@/types/api'

function SystemCard({ client, busy, onRotate, onRevoke }: { client: ApiClientView; busy: boolean; onRotate?: () => void; onRevoke?: () => void }) {
  const state = STATE[stateOf(client)]
  return (
    <div className={cn('flex flex-col gap-4 rounded-xl border bg-card p-5', client.revoked_at && 'bg-muted/30')}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl', client.revoked_at ? 'bg-muted text-muted-foreground' : 'bg-primary/10 text-primary')}>
            <Plug className="size-5" />
          </span>
          <div className="flex min-w-0 flex-col">
            <span className="truncate font-semibold">{client.name}</span>
            <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground" title={state.hint}>
              <span className={cn('size-2 shrink-0 rounded-full', state.dot)} /> {state.label}
            </span>
          </div>
        </div>
      </div>

      <dl className="grid grid-cols-3 gap-3 text-sm">
        <div className="flex flex-col">
          <dt className="text-xs text-muted-foreground">Último uso</dt>
          <dd title={client.last_used_at ? new Date(client.last_used_at).toLocaleString() : undefined}>{ago(client.last_used_at)}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-xs text-muted-foreground">Llamadas por minuto</dt>
          <dd>{client.rate_limit_per_minute}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-xs text-muted-foreground">{client.revoked_at ? 'Sin acceso desde' : 'Secreto cambiado'}</dt>
          <dd title={new Date(client.revoked_at ?? client.secret_rotated_at).toLocaleString()}>{ago(client.revoked_at ?? client.secret_rotated_at)}</dd>
        </div>
      </dl>

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3">
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none hover:text-foreground">Detalle técnico</summary>
          <div className="mt-2 flex items-center gap-1.5">
            <span>Identificador</span>
            <code className="text-foreground">{client.client_id}</code>
            <button type="button" className="hover:text-foreground" aria-label="Copiar el identificador" onClick={() => navigator.clipboard.writeText(client.client_id).then(() => toast.success('Copiado.'))}>
              <Copy className="size-3" />
            </button>
          </div>
          <div className="mt-1">Creado por {client.created_by}, {new Date(client.created_at).toLocaleDateString()}</div>
        </details>
        {onRotate && onRevoke && (
          <div className="flex gap-1">
            <Button size="sm" variant="outline" disabled={busy} onClick={onRotate}>
              <RefreshCw className="size-3.5" /> Cambiar secreto
            </Button>
            <Button size="sm" variant="ghost" className="text-destructive" disabled={busy} onClick={onRevoke}>
              <ShieldOff className="size-3.5" /> Quitar acceso
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

export function ApiClientsPage() {
  const { data: clients, isLoading, isError } = useApiClients()
  const action = useApiClientAction()
  const [dialog, setDialog] = useState<{ issued?: ApiClientWithSecret } | null>(null)
  const base = `${window.location.origin}/api`
  const all = clients ?? []
  const active = all.filter((c) => !c.revoked_at)
  const revoked = all.filter((c) => c.revoked_at)
  const count = (s: SystemState) => all.filter((c) => stateOf(c) === s).length

  const rotate = (c: ApiClientView) =>
    confirm(`¿Cambiar el secreto de «${c.name}»? El actual deja de funcionar ahora mismo: su equipo tendrá que usar el nuevo.`) &&
    action.mutate({ kind: 'rotate', id: c.id }, { onSuccess: (r) => setDialog({ issued: r as ApiClientWithSecret }), onError: (e) => toast.error(errorDetail(e)) })
  const revoke = (c: ApiClientView) =>
    confirm(`¿Quitar el acceso a «${c.name}»? No podrá volver a llamar a Veritium.`) &&
    action.mutate({ kind: 'revoke', id: c.id }, { onSuccess: () => toast.success(`«${c.name}» ya no tiene acceso.`), onError: (e) => toast.error(errorDetail(e)) })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Sistemas conectados</h1>
          <p className="text-muted-foreground">
            Los sistemas que llaman a Veritium desde su propio servidor. Cada uno tiene sus credenciales y su cuota de llamadas; puedes cambiarlas o cortarle el
            acceso sin afectar a los demás.
          </p>
        </div>
        <Button onClick={() => setDialog({})}>
          <Plus className="size-4" /> Conectar un sistema
        </Button>
      </div>

      {clients && all.length > 0 && (
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          {(['in_use', 'never', 'idle', 'revoked'] as SystemState[])
            .filter((s) => count(s))
            .map((s) => (
              <span key={s} className="inline-flex items-center gap-2" title={STATE[s].hint}>
                <span className={cn('size-2.5 rounded-full', STATE[s].dot)} />
                <span className="font-semibold tabular-nums">{count(s)}</span>
                <span className="text-muted-foreground">{STATE[s].label.toLowerCase()}</span>
              </span>
            ))}
        </div>
      )}

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar los sistemas: el servidor de Veritium no responde.</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {active.map((c) => (
            <SystemCard key={c.id} client={c} busy={action.isPending} onRotate={() => rotate(c)} onRevoke={() => revoke(c)} />
          ))}
          <button
            type="button"
            onClick={() => setDialog({})}
            className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center text-sm text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
          >
            <KeyRound className="size-5" />
            <span className="font-medium">Conectar un sistema</span>
            <span className="text-xs">{active.length ? 'Cada sistema con sus propias credenciales.' : 'Todavía no hay sistemas conectados.'}</span>
          </button>
        </div>
      )}

      {revoked.length > 0 && (
        <details className="group rounded-2xl border bg-muted/40">
          <summary className="cursor-pointer px-5 py-3 text-sm font-medium select-none">Sin acceso ({revoked.length})</summary>
          <div className="grid gap-4 border-t p-4 sm:p-5 lg:grid-cols-2">
            {revoked.map((c) => (
              <SystemCard key={c.id} client={c} busy={false} />
            ))}
          </div>
        </details>
      )}

      <details className="rounded-2xl border bg-muted/40 text-sm">
        <summary className="cursor-pointer px-5 py-3 font-medium select-none">Cómo se conecta un sistema (para su equipo técnico)</summary>
        <div className="flex flex-col gap-2 border-t px-5 py-4">
          <span>
            1. Pide un token con sus credenciales (OAuth2 <em>client credentials</em>). Dura 15 minutos; al vencer, pide otro.
          </span>
          <pre className="overflow-x-auto rounded-md bg-background p-3 text-xs">{`curl -X POST ${base}/auth/token \\
  -d grant_type=client_credentials \\
  -d client_id=$CLIENT_ID -d client_secret=$CLIENT_SECRET`}</pre>
          <span>2. Llama a la API con el token. Si supera su cuota recibe 429 y el header Retry-After con los segundos a esperar.</span>
          <pre className="overflow-x-auto rounded-md bg-background p-3 text-xs">{`curl ${base}/v1/cases -H "Authorization: Bearer $TOKEN"`}</pre>
          <span>
            La referencia completa de la API está en <code>/docs</code> del servicio.
          </span>
        </div>
      </details>

      {dialog && <CredentialsDialog issued={dialog.issued} onClose={() => setDialog(null)} />}
    </div>
  )
}
