// The state of a case's personal data on screen (VRT-58): hidden by default;
// whoever works the case asks to see them, and that stays recorded.
import { useState } from 'react'
import { Eye, EyeOff, Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { isAdmin } from '@/lib/auth'
import { useRevealCaseData, useSuppressCaseData } from '@/lib/queries'

const REMOVED: Record<string, string> = { suprimido: 'a pedido del titular', vencido: 'al vencer el plazo de conservación del proceso' }

/** An admin removes the case's personal data for good, e.g. when the person asks (Ley 29733). */
function SuppressButton({ caseId }: { caseId: string }) {
  const suppress = useSuppressCaseData()
  return (
    <Button
      size="sm"
      variant="ghost"
      className="ml-auto text-destructive"
      disabled={suppress.isPending}
      onClick={() => {
        const reason = prompt(
          'Se borrarán para siempre los archivos, lo leído y lo extraído de este expediente, y los textos que citan sus datos. Queda el expediente anonimizado (proceso, fechas, veredicto) y el registro.\n\n¿Por qué se suprimen? (p. ej. «Solicitud de cancelación del titular, carta 123»)',
        )?.trim()
        if (!reason) return
        if (reason.length < 5) return toast.error('Indica el motivo con un poco más de detalle.')
        suppress.mutate(
          { caseId, reason },
          { onSuccess: () => toast.success('Datos personales suprimidos.'), onError: (e) => toast.error(errorDetail(e)) },
        )
      }}
    >
      <Trash2 className="size-3.5" /> Suprimir datos
    </Button>
  )
}

export function PersonalDataBar({
  caseId,
  visible,
  canReveal,
  compact = false,
  removed,
}: {
  caseId: string
  visible: boolean
  canReveal: boolean
  compact?: boolean
  removed?: { at: string | null; reason: string | null; retentionDays: number | null }
}) {
  const reveal = useRevealCaseData()
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')

  if (removed?.at) {
    return (
      <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground">
        <Trash2 className="size-4" />
        <span>
          Datos personales suprimidos el {new Date(removed.at).toLocaleDateString('es-PE', { dateStyle: 'medium' })} {REMOVED[removed.reason ?? ''] ?? ''}. El
          expediente queda anonimizado.
        </span>
      </div>
    )
  }
  const keeping = removed && !compact && (
    <span className="text-xs">{removed.retentionDays ? `Se conservan ${removed.retentionDays} días desde la decisión.` : 'Sin plazo de conservación.'}</span>
  )
  const suppressible = !compact && isAdmin() && <SuppressButton caseId={caseId} />

  if (visible) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-amber-500/50 bg-amber-50 px-3 py-2 text-sm dark:bg-amber-950/30">
        <Eye className="size-4 text-amber-600" />
        <span>Datos personales visibles por unos minutos. Tu consulta quedó registrada.</span>
        {keeping}
        {suppressible}
      </div>
    )
  }
  if (!canReveal) {
    return compact ? null : (
      <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground">
        <EyeOff className="size-4" />
        <span>Los datos personales se muestran ocultos; tu rol no permite verlos.</span>
        {keeping}
      </div>
    )
  }
  const submit = () =>
    reveal.mutate(
      { caseId, reason: reason.trim() || undefined },
      { onSuccess: () => setAsking(false), onError: () => toast.error('No se pudo mostrar los datos.') },
    )
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground">
      <EyeOff className="size-4" />
      <span>Datos personales ocultos.</span>
      {asking ? (
        <>
          <Input
            autoFocus
            placeholder="Para qué los necesitas (opcional)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            className="h-8 w-64"
          />
          <Button size="sm" onClick={submit} disabled={reveal.isPending}>
            {reveal.isPending && <Loader2 className="size-3.5 animate-spin" />} Ver datos
          </Button>
          <span className="text-xs">Quedará registrado quién los vio y cuándo.</span>
        </>
      ) : (
        <Button size="sm" variant="outline" onClick={() => setAsking(true)}>
          <Eye className="size-3.5" /> Ver datos
        </Button>
      )}
      {keeping}
      {suppressible}
    </div>
  )
}
