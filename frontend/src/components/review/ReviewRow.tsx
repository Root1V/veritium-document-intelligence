// One datum to review (VRT-39, VRT-72, VRT-108): what was read and what the
// document says, why it is here — a finding, or low confidence in a traffic
// light — and what the AI suggests, in two lines. «Corregir» is the main
// action; «Es correcto» keeps the value, with its reason written right here.
// Both stay in the audit. Used by the review queue and by the findings page.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Loader2, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { PersonalDataBar } from '@/components/cases/PersonalDataBar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute } from '@/lib/auth'
import { useCorrectionReasons, useDismissInvestigation, useDismissReviewItem, useSubmitCorrection } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ReviewItem } from '@/types/api'

const REASON_LABEL: Record<ReviewItem['reason'], string> = {
  low_confidence: 'Lectura dudosa',
  validation_issue: 'No pasó una validación',
  investigation: 'Sugerencia de la IA',
}

const show = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v))
const confidenceTone = (c: number) => (c >= 0.95 ? 'bg-emerald-500' : c >= 0.85 ? 'bg-amber-500' : 'bg-red-500')

type Mode = 'idle' | 'correct' | 'confirm'

export function ReviewRow({ item }: { item: ReviewItem }) {
  const submit = useSubmitCorrection()
  const dismissItem = useDismissReviewItem()
  const dismissSuggestion = useDismissInvestigation()
  const { data: reasons } = useCorrectionReasons()
  const [mode, setMode] = useState<Mode>('idle')
  const [value, setValue] = useState(show(item.current_value.value) === '—' ? '' : String(item.current_value.value))
  const [reasonCode, setReasonCode] = useState('')
  const [justification, setJustification] = useState('')
  const [more, setMore] = useState(false)
  const may = canExecute()
  const reason = reasons?.find((r) => r.code === reasonCode)
  const suggestion = item.suggestion

  // Fills the correction with the suggestion; the reviewer still chooses the reason and saves.
  function applySuggestion() {
    if (!suggestion) return
    if (suggestion.action === 'confirmar_dato') return setMode('confirm')
    if (suggestion.action === 'corregir_dato') setValue(String(suggestion.value ?? ''))
    setMode('correct')
  }

  function saveCorrection() {
    if (!reason) return void toast.error('Elige el motivo de la corrección.')
    if (reason.requires_justification && justification.trim().length < 5) return void toast.error(`«${reason.label}» necesita un sustento.`)
    submit.mutate(
      { reviewItemId: item.id, body: { corrected_value: value, reason_code: reason.code, justification: justification.trim() || null } },
      { onSuccess: () => toast.success('Corrección guardada.'), onError: (e) => toast.error(errorDetail(e)) },
    )
  }

  function saveConfirmation() {
    if (justification.trim().length < 5) return void toast.error('Di por qué el valor es correcto (mínimo 5 caracteres).')
    dismissItem.mutate(
      { reviewItemId: item.id, justification: justification.trim() },
      { onSuccess: () => toast.success('Confirmado como correcto.'), onError: (e) => toast.error(errorDetail(e)) },
    )
  }

  return (
    <div className="flex flex-col gap-2.5 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{item.label}</span>
            {item.role && <span className="rounded bg-muted px-1.5 py-0.5 text-xs capitalize">{item.role}</span>}
          </span>
          <span className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
            {item.document_type_name ?? 'Documento sin tipo registrado'} ·
            <Link to={`/documents/${item.document_id}`} className="inline-flex items-center gap-1 text-primary hover:underline">
              <FileText className="size-3" /> {item.filename}
            </Link>
            {item.page != null && `· pág. ${item.page + 1}`}
          </span>
        </div>
        <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          {REASON_LABEL[item.reason] ?? item.reason}
          <span className="inline-flex items-center gap-1" title="Qué tan seguro estaba el sistema al leerlo">
            <span className={cn('size-2 rounded-full', confidenceTone(item.confidence))} /> {Math.round(item.confidence * 100)}%
          </span>
        </span>
      </div>

      {item.finding && <p className="text-sm text-amber-700 dark:text-amber-400">{item.finding}</p>}

      <p className="text-sm">
        <span className="text-muted-foreground">Leído: </span>
        <span className="font-semibold">{show(item.current_value.value)}</span>
        {item.source_text && <span className="text-xs text-muted-foreground"> · en el documento dice «{item.source_text}»</span>}
      </p>

      {suggestion && (
        <div className="flex flex-col gap-0.5 border-l-2 border-sky-500/60 pl-2 text-xs">
          <span className="inline-flex items-center gap-1 font-medium text-sky-700 dark:text-sky-300">
            <Sparkles className="size-3" /> La IA sugiere: {suggestion.action_label.toLowerCase()}
            {suggestion.action === 'corregir_dato' && <> → «{show(suggestion.value)}»</>}
          </span>
          <p className={cn('text-muted-foreground', !more && 'line-clamp-2')}>{suggestion.diagnosis}</p>
          <span className="flex gap-3">
            <button type="button" onClick={() => setMore(!more)} className="text-sky-700 hover:underline dark:text-sky-300">
              {more ? 'Ver menos' : 'Ver más'}
            </button>
            {may && item.personal_data_visible && mode === 'idle' && (suggestion.action === 'corregir_dato' || suggestion.action === 'confirmar_dato') && (
              <button type="button" onClick={applySuggestion} className="font-medium text-sky-700 hover:underline dark:text-sky-300">
                Usar sugerencia
              </button>
            )}
            {may && (
              <button
                type="button"
                className="text-muted-foreground hover:underline"
                onClick={() => dismissSuggestion.mutate(suggestion.investigation_id, { onError: (e) => toast.error(errorDetail(e)) })}
              >
                Descartar sugerencia
              </button>
            )}
          </span>
        </div>
      )}

      {may &&
        (!item.personal_data_visible ? (
          // A masked value cannot be corrected: see it first (VRT-58).
          <PersonalDataBar caseId={item.case_id} visible={false} canReveal={item.can_reveal} compact />
        ) : mode === 'idle' ? (
          <div className="flex items-center gap-2">
            <Button size="sm" className="h-8" onClick={() => setMode('correct')}>
              Corregir
            </Button>
            <Button size="sm" variant="outline" className="h-8" onClick={() => setMode('confirm')}>
              Es correcto
            </Button>
          </div>
        ) : mode === 'correct' ? (
          <div className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3">
            <div className="flex flex-wrap gap-2">
              <Input value={value} onChange={(e) => setValue(e.target.value)} className="h-8 max-w-xs" aria-label="Valor correcto" autoFocus />
              <Select value={reasonCode} onValueChange={setReasonCode}>
                <SelectTrigger className="h-8 w-60">
                  <SelectValue placeholder="Por qué se corrige" />
                </SelectTrigger>
                <SelectContent>
                  {(reasons ?? [])
                    .filter((r) => r.code !== 'confirmed_correct')
                    .map((r) => (
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
              className="h-8 text-sm"
            />
            <div className="flex gap-2">
              <Button size="sm" className="h-8" disabled={submit.isPending} onClick={saveCorrection}>
                {submit.isPending && <Loader2 className="size-3.5 animate-spin" />} Guardar corrección
              </Button>
              <Button size="sm" variant="ghost" className="h-8" onClick={() => setMode('idle')}>
                Cancelar
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3">
            <span className="text-xs text-muted-foreground">El valor se queda como está. Di por qué es correcto: queda en la auditoría.</span>
            <Input value={justification} onChange={(e) => setJustification(e.target.value)} placeholder="p. ej. El maestro de empleados está desactualizado" className="h-8 text-sm" autoFocus />
            <div className="flex gap-2">
              <Button size="sm" className="h-8" disabled={dismissItem.isPending} onClick={saveConfirmation}>
                {dismissItem.isPending && <Loader2 className="size-3.5 animate-spin" />} Confirmar
              </Button>
              <Button size="sm" variant="ghost" className="h-8" onClick={() => setMode('idle')}>
                Cancelar
              </Button>
            </div>
          </div>
        ))}
    </div>
  )
}
