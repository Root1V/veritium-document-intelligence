// The state of a case's personal data on screen (VRT-58): hidden by default;
// whoever works the case asks to see them, and that stays recorded.
import { useState } from 'react'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useRevealCaseData } from '@/lib/queries'

export function PersonalDataBar({ caseId, visible, canReveal, compact = false }: { caseId: string; visible: boolean; canReveal: boolean; compact?: boolean }) {
  const reveal = useRevealCaseData()
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')

  if (visible) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-amber-500/50 bg-amber-50 px-3 py-2 text-sm dark:bg-amber-950/30">
        <Eye className="size-4 text-amber-600" />
        <span>Datos personales visibles por unos minutos. Tu consulta quedó registrada.</span>
      </div>
    )
  }
  if (!canReveal) {
    return compact ? null : (
      <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground">
        <EyeOff className="size-4" />
        <span>Los datos personales se muestran ocultos; tu rol no permite verlos.</span>
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
    </div>
  )
}
