// Connecting a system (VRT-65, VRT-97) in two steps: its name and quota,
// then its credentials — shown this once, to copy and hand over by a safe
// channel. A new secret after a rotation opens straight on the second step.
import { useState } from 'react'
import { Copy, KeyRound, Loader2, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { useApiClientAction } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ApiClientWithSecret } from '@/types/api'

const QUOTAS = [
  { value: '', label: 'La normal', hint: 'La que Veritium da a todo sistema.' },
  { value: '600', label: 'Alta · 600 por minuto', hint: 'Para un sistema que envía mucho, como un canal masivo.' },
  { value: 'custom', label: 'Otra', hint: 'Una cifra exacta de llamadas por minuto.' },
]

function Credentials({ client }: { client: ApiClientWithSecret }) {
  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast.success('Copiado.'))
  return (
    <div className="flex flex-col gap-4">
      <p className="flex items-start gap-2 rounded-lg bg-amber-500/10 px-3 py-2.5 text-sm text-amber-800 dark:text-amber-300">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        Cópialas ahora y entrégalas al equipo de «{client.name}» por un canal seguro. El secreto no se volverá a mostrar.
      </p>
      {[
        ['Identificador (client_id)', client.client_id],
        ['Secreto (client_secret)', client.client_secret],
      ].map(([label, value]) => (
        <label key={label} className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
          <div className="flex gap-2">
            <Input readOnly value={value} onFocus={(e) => e.target.select()} className="font-mono text-xs" />
            <Button variant="outline" onClick={() => copy(value)} aria-label={`Copiar ${label}`}>
              <Copy className="size-4" />
            </Button>
          </div>
        </label>
      ))}
    </div>
  )
}

export function CredentialsDialog({ issued, onClose }: { issued?: ApiClientWithSecret; onClose: () => void }) {
  const action = useApiClientAction()
  const [name, setName] = useState('')
  const [quota, setQuota] = useState('')
  const [custom, setCustom] = useState('')
  const [created, setCreated] = useState<ApiClientWithSecret | undefined>(issued)
  const rate = quota === 'custom' ? Number(custom) : quota ? Number(quota) : undefined
  const problem =
    name.trim().length < 3 ? 'Ponle un nombre (mínimo 3 letras).' : quota === 'custom' && !(rate! >= 1 && rate! <= 10_000) ? 'La cuota va de 1 a 10 000 por minuto.' : null

  return (
    <Dialog open onOpenChange={(open) => !open && !created && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-lg" showCloseButton={!created}>
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>{created ? (issued ? 'Nuevo secreto' : 'Credenciales listas') : 'Conectar un sistema'}</DialogTitle>
          <DialogDescription>
            {created ? `Con esto «${created.name}» se conecta a Veritium.` : 'Podrá enviar y consultar expedientes, sesiones de carga y cargas masivas; nada de administración.'}
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          {created ? (
            <Credentials client={created} />
          ) : (
            <>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">Nombre del sistema</span>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="p. ej. Core bancario" autoFocus />
              </label>
              <div className="flex flex-col gap-2">
                <span className="text-sm font-medium">Cuántas llamadas puede hacer</span>
                {QUOTAS.map((q) => {
                  const chosen = quota === q.value
                  return (
                    <button
                      key={q.value}
                      type="button"
                      onClick={() => setQuota(q.value)}
                      className={cn('flex items-start gap-3 rounded-lg border p-3 text-left transition', chosen ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:border-primary/40')}
                    >
                      <span className={cn('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border', chosen && 'border-primary bg-primary')}>
                        {chosen && <span className="size-1.5 rounded-full bg-primary-foreground" />}
                      </span>
                      <span className="flex flex-1 flex-col">
                        <span className="text-sm font-medium">{q.label}</span>
                        <span className="text-xs text-muted-foreground">{q.hint}</span>
                      </span>
                    </button>
                  )
                })}
                {quota === 'custom' && (
                  <div className="flex items-center gap-2 pl-7">
                    <Input type="number" min={1} max={10_000} value={custom} onChange={(e) => setCustom(e.target.value)} className="w-32" />
                    <span className="text-sm text-muted-foreground">llamadas por minuto</span>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <DialogFooter className="flex-row items-center gap-2 border-t px-6 py-4 sm:justify-between">
          {created ? (
            <>
              <span />
              <Button onClick={onClose}>Ya las guardé</Button>
            </>
          ) : (
            <>
              <span className="text-xs text-muted-foreground">{problem}</span>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={onClose}>
                  Cancelar
                </Button>
                <Button
                  disabled={!!problem || action.isPending}
                  onClick={() =>
                    action.mutate(
                      { kind: 'create', name: name.trim(), rateLimit: rate },
                      { onSuccess: (c) => setCreated(c as ApiClientWithSecret), onError: (e) => toast.error(errorDetail(e)) },
                    )
                  }
                >
                  {action.isPending ? <Loader2 className="size-4 animate-spin" /> : <KeyRound className="size-4" />} Crear credenciales
                </Button>
              </div>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
