// A new rule in three questions (VRT-90): what it is about, what it compares
// against, and the rule in words; Veritium writes the condition and its test
// cases, and the draft waits on the page to be tried and switched on. CEL by
// hand stays available, folded.
import { useState } from 'react'
import { Loader2, Wand2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Choice } from '@/components/profiles/RequirementRow'
import { errorDetail } from '@/lib/apiErrors'
import { fieldName } from '@/lib/documentTypes'
import { useCreateManualRule, useDocumentTypeCatalog, useDraftValidationRule, useSemanticCatalog } from '@/lib/queries'
import { COMPARES, SEVERITY } from '@/lib/validationRules'
import { cn } from '@/lib/utils'
import type { RuleCelCategory } from '@/types/api'

const WHOLE = '__whole'
const EXAMPLES = {
  attribute: ['El ingreso neto mensual debe ser de al menos 1025 soles', 'El monto solicitado no puede pasar de 100 000 soles'],
  document: ['El neto debe ser igual al bruto menos los descuentos, con 1 sol de tolerancia', 'La fecha de emisión no puede tener más de 3 meses'],
}

export function NewRuleDialog({ onClose }: { onClose: () => void }) {
  const { data: types } = useDocumentTypeCatalog()
  const { data: semantic } = useSemanticCatalog()
  const draft = useDraftValidationRule()
  const manual = useCreateManualRule()
  const [target, setTarget] = useState<'attribute' | 'document'>('attribute')
  const [attribute, setAttribute] = useState('')
  const [documentType, setDocumentType] = useState('')
  const [field, setField] = useState(WHOLE)
  const [category, setCategory] = useState<RuleCelCategory>('self')
  const [description, setDescription] = useState('')
  const [questions, setQuestions] = useState<string[]>([])
  const [byHand, setByHand] = useState(false)
  const [hand, setHand] = useState({ id: '', cel: '', severity: 'warning' as 'info' | 'warning' | 'error', pass: '', fail: '' })
  const pending = draft.isPending || manual.isPending

  const catalog = semantic?.catalog
  const entityName = (key: string) => catalog?.entities.find((e) => e.key === key.split('.')[0])?.name ?? ''
  const type = types?.registered.find((t) => t.name === documentType)
  const scope = target === 'attribute' ? { attribute } : { document_type: documentType }
  const fieldPath = target === 'document' && field !== WHOLE ? field : undefined
  const problem =
    target === 'attribute' && !attribute
      ? 'Elige el dato.'
      : target === 'document' && !documentType
        ? 'Elige el tipo de documento.'
        : byHand
          ? !hand.id.trim() || !hand.cel.trim() || !hand.pass.trim() || !hand.fail.trim()
            ? 'Completa el identificador, la condición y los dos mensajes.'
            : null
          : !description.trim()
            ? 'Describe la regla.'
            : null

  const done = () => {
    toast.success('Regla lista para revisar: pruébala y actívala.')
    onClose()
  }

  function submit() {
    if (byHand) {
      manual.mutate(
        { rule_id_suffix: hand.id.trim(), ...scope, category, field_path: fieldPath, condition_cel: hand.cel, severity: hand.severity, message_pass: hand.pass, message_fail: hand.fail },
        { onSuccess: done, onError: (e) => toast.error(errorDetail(e)) },
      )
      return
    }
    draft.mutate(
      { description, ...scope, category, field_path: fieldPath, existing_fields_hint: type?.fields.map((f) => f.name) },
      {
        onSuccess: (data) => (data.outcome === 'ambiguous' ? setQuestions(data.questions) : done()),
        onError: (e) => toast.error(errorDetail(e)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>Nueva regla</DialogTitle>
          <DialogDescription>Descríbela en palabras: Veritium escribe la condición y sus casos de prueba, y tú la pruebas antes de activarla.</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 py-5">
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">1. ¿Sobre qué es?</h3>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  ['attribute', 'Un dato', 'en cualquier documento que lo traiga'],
                  ['document', 'Un tipo de documento', 'sus campos'],
                ] as const
              ).map(([value, label, hint]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTarget(value)}
                  className={cn('flex flex-col rounded-lg border px-3 py-2 text-left text-sm transition', target === value ? 'border-primary bg-primary/5' : 'hover:bg-muted/50')}
                >
                  <span className="font-medium">{label}</span>
                  <span className="text-xs text-muted-foreground">{hint}</span>
                </button>
              ))}
            </div>
            {target === 'attribute' ? (
              <Choice
                value={attribute}
                placeholder="Elige el dato, p. ej. Ingreso neto mensual"
                className="w-full"
                options={(catalog?.attributes ?? []).map((a) => ({ value: a.key, label: `${entityName(a.key)} · ${a.name}` }))}
                onChange={setAttribute}
              />
            ) : (
              <div className="flex flex-wrap gap-2">
                <Choice
                  value={documentType}
                  placeholder="Tipo de documento"
                  className="w-64"
                  options={(types?.registered ?? []).map((t) => ({ value: t.name, label: t.display_name }))}
                  onChange={(v) => {
                    setDocumentType(v)
                    setField(WHOLE)
                  }}
                />
                {type && (
                  <Choice
                    value={field}
                    className="min-w-52 flex-1"
                    options={[{ value: WHOLE, label: 'Todo el documento' }, ...type.fields.map((f) => ({ value: f.name, label: fieldName(f) }))]}
                    onChange={setField}
                  />
                )}
              </div>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">2. ¿Con qué se compara?</h3>
            <div className="grid gap-2 sm:grid-cols-3">
              {COMPARES.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => setCategory(c.value)}
                  className={cn('flex flex-col gap-0.5 rounded-lg border px-3 py-2 text-left text-sm transition', category === c.value ? 'border-primary bg-primary/5' : 'hover:bg-muted/50')}
                >
                  <span className="font-medium">{c.label}</span>
                  <span className="text-xs text-muted-foreground">{c.hint}</span>
                </button>
              ))}
            </div>
          </section>

          {!byHand && (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold">3. La regla, en palabras</h3>
              <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder={EXAMPLES[target][0]} rows={3} />
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                Ejemplos:
                {EXAMPLES[target].map((ex) => (
                  <button key={ex} type="button" onClick={() => setDescription(ex)} className="rounded-full border px-2 py-0.5 hover:bg-muted hover:text-foreground">
                    {ex}
                  </button>
                ))}
              </div>
              {questions.length > 0 && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
                  <p className="font-medium">Falta precisar algo. Veritium no inventa lo que no se dice; agrégalo a la descripción:</p>
                  <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                    {questions.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          <details open={byHand} onToggle={(e) => setByHand((e.target as HTMLDetailsElement).open)} className="text-xs text-muted-foreground">
            <summary className="w-fit cursor-pointer select-none hover:text-foreground">Prefiero escribir la condición (CEL)</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                Identificador
                <Input value={hand.id} onChange={(e) => setHand({ ...hand, id: e.target.value })} placeholder="p. ej. neto_minimo" className="h-8 font-mono text-xs" />
              </label>
              <label className="flex flex-col gap-1.5">
                Gravedad si falla
                <Choice value={hand.severity} className="h-8" options={Object.entries(SEVERITY).map(([value, s]) => ({ value, label: s.label }))} onChange={(v) => setHand({ ...hand, severity: v as typeof hand.severity })} />
              </label>
              <label className="flex flex-col gap-1.5 sm:col-span-2">
                Condición
                <Textarea value={hand.cel} onChange={(e) => setHand({ ...hand, cel: e.target.value })} placeholder={target === 'attribute' ? 'value >= 1025.0' : 'has(doc.net_pay) && doc.net_pay > 0.0'} className="font-mono text-xs" rows={2} />
              </label>
              <label className="flex flex-col gap-1.5">
                Mensaje si cumple
                <Input value={hand.pass} onChange={(e) => setHand({ ...hand, pass: e.target.value })} className="h-8 text-xs" />
              </label>
              <label className="flex flex-col gap-1.5">
                Mensaje si no cumple
                <Input value={hand.fail} onChange={(e) => setHand({ ...hand, fail: e.target.value })} className="h-8 text-xs" />
              </label>
            </div>
          </details>
        </div>

        <DialogFooter className="flex-row items-center gap-2 border-t px-6 py-4 sm:justify-between">
          <span className="text-xs text-muted-foreground">{problem}</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button onClick={submit} disabled={!!problem || pending}>
              {pending ? <Loader2 className="size-4 animate-spin" /> : !byHand && <Wand2 className="size-4" />}
              {byHand ? 'Crear borrador' : pending ? 'Redactando…' : 'Redactar con IA'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
