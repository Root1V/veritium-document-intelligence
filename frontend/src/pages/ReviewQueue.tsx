import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useCorrectionReasons, useDismissInvestigation, useInvestigationStats, useReviewQueue, useSubmitCorrection } from '@/lib/queries'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute } from '@/lib/auth'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ReviewItem } from '@/types/api'

const REASON_LABEL: Record<string, string> = {
  low_confidence: 'Confianza baja',
  validation_issue: 'Problema de validación',
  investigation: 'Sugerencia del investigador',
}

function ReviewRow({ item }: { item: ReviewItem }) {
  const submitCorrection = useSubmitCorrection()
  const { data: reasons } = useCorrectionReasons()
  const [correcting, setCorrecting] = useState(false)
  const [value, setValue] = useState(String(item.current_value.value ?? ''))
  const [reasonCode, setReasonCode] = useState('')
  const [justification, setJustification] = useState('')
  const canCorrect = canExecute()
  const reason = reasons?.find((r) => r.code === reasonCode)
  const dismiss = useDismissInvestigation()

  // Fills the correction with the suggestion; the reviewer still chooses the reason and saves.
  function applySuggestion() {
    const suggestion = item.suggestion
    if (!suggestion) return
    if (suggestion.action === 'corregir_dato') setValue(String(suggestion.value ?? ''))
    if (suggestion.action === 'confirmar_dato') {
      setValue(String(item.current_value.value ?? ''))
      setReasonCode('confirmed_correct')
    }
    setCorrecting(true)
  }

  function handleSubmit() {
    if (!reason) {
      toast.error('Elige el motivo de la corrección.')
      return
    }
    if (reason.requires_justification && justification.trim().length < 5) {
      toast.error(`"${reason.label}" requiere un sustento.`)
      return
    }
    submitCorrection.mutate(
      { reviewItemId: item.id, body: { corrected_value: value, reason_code: reason.code, justification: justification.trim() || null } },
      {
        onSuccess: () => toast.success('Corrección guardada.'),
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{item.label}</span>
            {item.role && (
              <Badge variant="secondary" className="text-xs">
                {item.role}
              </Badge>
            )}
            <Badge variant="outline" className="text-xs">
              {REASON_LABEL[item.reason] ?? item.reason}
            </Badge>
            <Badge variant="outline" className="text-xs">
              confianza {(item.confidence * 100).toFixed(0)}%
            </Badge>
          </div>
          {item.description && <span className="text-xs text-muted-foreground">{item.description}</span>}
          <span className="text-xs text-muted-foreground">
            {item.document_type_name ?? 'Documento sin tipo registrado'} ·{' '}
            <Link to={`/documents/${item.document_id}`} className="underline-offset-4 hover:underline">
              {item.filename}
            </Link>
            {item.page != null && ` · pág. ${item.page + 1}`} · expediente{' '}
            <Link to={`/cases/${item.case_id}`} className="underline-offset-4 hover:underline">
              {item.case_ref ?? item.case_id.slice(0, 8)}
            </Link>
          </span>
        </div>

        {item.finding && <p className="text-sm text-amber-700 dark:text-amber-400">{item.finding}</p>}
        {item.suggestion && (
          <div className="flex flex-col gap-1 rounded-md border border-sky-500/30 bg-sky-50/50 p-2 text-sm dark:bg-sky-950/20">
            <span className="text-xs font-medium uppercase tracking-wide text-sky-700 dark:text-sky-400">
              Sugerencia del investigador · {item.suggestion.action_label}
              {item.suggestion.confidence !== null && ` · confianza ${Math.round(item.suggestion.confidence * 100)}%`}
            </span>
            <span>{item.suggestion.diagnosis}</span>
            {canCorrect && (
              <div className="flex flex-wrap items-center gap-2">
                {item.suggestion.action === 'corregir_dato' && (
                  <span>
                    Valor sugerido: <strong>{String(item.suggestion.value)}</strong>
                  </span>
                )}
                <Button size="sm" variant="outline" onClick={applySuggestion}>
                  Usar sugerencia
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => dismiss.mutate(item.suggestion!.investigation_id, { onError: (e) => toast.error(errorDetail(e)) })}
                >
                  Descartar
                </Button>
              </div>
            )}
          </div>
        )}
        {item.source_text && (
          <p className="text-xs text-muted-foreground">
            Texto en el documento: <span className="font-mono">«{item.source_text}»</span>
          </p>
        )}

        {!correcting ? (
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-muted-foreground">Valor actual: {String(item.current_value.value ?? '—')}</span>
            {canCorrect && (
              <Button size="sm" variant="outline" onClick={() => setCorrecting(true)}>
                Corregir
              </Button>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Input value={value} onChange={(e) => setValue(e.target.value)} className="max-w-sm" aria-label="Valor corregido" />
              <Select
                value={reasonCode}
                onValueChange={(code) => {
                  setReasonCode(code)
                  if (code === 'confirmed_correct') setValue(String(item.current_value.value ?? ''))
                }}
              >
                <SelectTrigger className="w-60">
                  <SelectValue placeholder="Motivo (obligatorio)" />
                </SelectTrigger>
                <SelectContent>
                  {(reasons ?? []).map((r) => (
                    <SelectItem key={r.code} value={r.code}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {reason && <span className="text-xs text-muted-foreground">{reason.description}</span>}
            <Input
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder={reason?.requires_justification ? 'Sustento (obligatorio para este motivo)' : 'Sustento (opcional)'}
              className="max-w-xl text-sm"
            />
            <div className="flex gap-2">
              <Button size="sm" disabled={submitCorrection.isPending} onClick={handleSubmit}>
                {submitCorrection.isPending && <Loader2 className="size-3.5 animate-spin" />}
                Guardar
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setCorrecting(false)}>
                Cancelar
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function ReviewQueuePage() {
  const { data: items, isLoading } = useReviewQueue()
  const { data: stats } = useInvestigationStats()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Cola de revisión</h1>
          <p className="text-muted-foreground">Campos con baja confianza o con observaciones de validación.</p>
        </div>
        {stats && stats.investigated > 0 && (
          <div className="rounded-md border px-3 py-2 text-sm" title="De las correcciones que sugirió el investigador y que alguien ya resolvió.">
            Sugerencias del investigador:{' '}
            <strong>{stats.acceptance_rate === null ? '—' : `${Math.round(stats.acceptance_rate * 100)}% aceptadas`}</strong>
            <span className="text-xs text-muted-foreground">
              {' '}
              · {stats.accepted} aplicadas, {stats.overridden} corregidas de otra forma, {stats.dismissed} descartadas
            </span>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : !items || items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No hay elementos pendientes de revisión.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {items.map((item) => (
            <ReviewRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
