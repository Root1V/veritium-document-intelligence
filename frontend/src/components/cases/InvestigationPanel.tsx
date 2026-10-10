// What the discrepancy investigator (VRT-66) found about one finding: its
// diagnosis, the likely cause, what it suggests, and the evidence — each
// quote marked as found (or not) in the document. It never decides: the
// reviewer applies the suggestion in the review queue, or dismisses it.
import { CheckCircle2, CircleAlert, Loader2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute } from '@/lib/auth'
import { useDismissInvestigation } from '@/lib/queries'
import type { Investigation } from '@/types/api'

const OUTCOME: Record<Investigation['outcome'], string | null> = {
  pending: null,
  accepted: 'Sugerencia aplicada',
  overridden: 'Se corrigió de otra forma',
  dismissed: 'Descartada',
}

export function InvestigationPanel({
  investigation: inv,
  onEvidence,
  onRetry,
}: {
  investigation: Investigation
  onEvidence: (documentId: string, page: number) => void
  onRetry?: () => void
}) {
  const dismiss = useDismissInvestigation()
  if (inv.status === 'running')
    return (
      <div className="flex items-center gap-2 rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" /> Investigando el hallazgo…
      </div>
    )
  if (inv.status === 'failed')
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
        <span>No se pudo investigar este hallazgo: el modelo no respondió como se esperaba. Puedes intentarlo de nuevo.</span>
        {onRetry && (
          <Button size="sm" variant="outline" className="h-7" onClick={onRetry}>
            Reintentar
          </Button>
        )}
        {inv.error && (
          <details>
            <summary className="cursor-pointer">Detalle técnico</summary>
            {inv.error}
          </details>
        )}
      </div>
    )
  return (
    <div className="flex flex-col gap-2 rounded-md border border-sky-500/30 bg-sky-50/50 p-3 text-sm dark:bg-sky-950/20">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-sky-700 dark:text-sky-400">Investigación</span>
        {inv.cause_label && <Badge variant="outline">{inv.cause_label}</Badge>}
        {inv.action_label && <Badge variant="secondary">{inv.action_label}</Badge>}
        {inv.confidence !== null && <span className="text-xs text-muted-foreground">confianza {Math.round(inv.confidence * 100)}%</span>}
        {OUTCOME[inv.outcome] && <Badge variant="outline">{OUTCOME[inv.outcome]}</Badge>}
      </div>
      <p>{inv.diagnosis}</p>
      {inv.action === 'corregir_dato' && (
        <p className="text-sm">
          Valor sugerido: <strong>{String(inv.suggested_value)}</strong>
          {inv.outcome === 'pending' && (
            <span className="text-xs text-muted-foreground">
              {' '}
              · aplícalo desde la{' '}
              <Link to="/review" className="underline">
                cola de revisión
              </Link>
            </span>
          )}
        </p>
      )}
      {inv.evidence.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs">
          {inv.evidence.map((e, i) => (
            <li key={i}>
              <button
                type="button"
                className="flex items-start gap-1.5 text-left hover:underline disabled:no-underline"
                disabled={!e.document_id}
                onClick={() => e.document_id && onEvidence(e.document_id, Math.max(0, (e.page ?? 1) - 1))}
              >
                {e.verified ? (
                  <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />
                ) : (
                  <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
                )}
                <span>
                  <span className="text-muted-foreground">
                    {e.document}
                    {e.page ? ` · pág. ${e.page}` : ''}:
                  </span>{' '}
                  «{e.text}»{!e.verified && <span className="text-amber-700 dark:text-amber-400"> (no se encontró tal cual en el documento)</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {inv.outcome === 'pending' && canExecute() && (
          <Button
            size="sm"
            variant="ghost"
            disabled={dismiss.isPending}
            onClick={() => dismiss.mutate(inv.id, { onError: (e) => toast.error(errorDetail(e)) })}
          >
            Descartar sugerencia
          </Button>
        )}
        {inv.tools_used.length > 0 && (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Cómo lo investigó</summary>
            {inv.tools_used.join(' → ')}
          </details>
        )}
      </div>
    </div>
  )
}
