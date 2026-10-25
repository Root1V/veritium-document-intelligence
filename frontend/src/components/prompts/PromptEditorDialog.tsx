// Proposing a change to an instruction (VRT-63, VRT-93): the text, with the
// parts the platform fills in checked as you type, and the reason, which
// stays in the audit. It is saved as a draft, never put in effect from here.
import { useState } from 'react'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { errorDetail } from '@/lib/apiErrors'
import { FILLED } from '@/lib/prompts'
import { useSavePromptDraft } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { PromptView } from '@/types/api'

export function PromptEditorDialog({ prompt, onClose }: { prompt: PromptView; onClose: () => void }) {
  const save = useSavePromptDraft()
  const [text, setText] = useState(prompt.draft?.text ?? prompt.text)
  const [reason, setReason] = useState(prompt.draft?.reason ?? '')
  const missing = prompt.placeholders.filter((p) => !text.includes(`{${p}}`))
  const problem = text === prompt.text ? 'Aún no cambiaste el texto.' : missing.length ? 'Faltan partes que completa la plataforma.' : reason.trim().length < 10 ? 'Explica por qué lo cambias (mínimo 10 caracteres).' : null

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[92svh] flex-col gap-0 p-0 sm:max-w-4xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>{prompt.draft ? 'Editar el borrador' : 'Proponer un cambio'} · {prompt.label}</DialogTitle>
          <DialogDescription>Se guarda como borrador: lo que se procesa sigue usando la versión en uso hasta que lo publiques.</DialogDescription>
        </DialogHeader>

        <div className="grid min-h-0 flex-1 gap-5 overflow-y-auto px-6 py-5 lg:grid-cols-[1fr_16rem]">
          <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-[50svh] font-mono text-xs leading-relaxed" />
          <aside className="flex flex-col gap-4 text-sm">
            {prompt.placeholders.length > 0 && (
              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-muted-foreground">Partes que completa la plataforma</span>
                {prompt.placeholders.map((p) => {
                  const ok = !missing.includes(p)
                  return (
                    <div key={p} className="flex items-start gap-2">
                      {ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-red-600" />}
                      <span className="flex flex-col">
                        <code className={cn('text-xs', !ok && 'text-red-700 dark:text-red-400')}>{`{${p}}`}</code>
                        <span className="text-xs text-muted-foreground">{FILLED[p] ?? 'un dato del caso'}</span>
                      </span>
                    </div>
                  )
                })}
                <span className="text-xs text-muted-foreground">Para una llave literal escribe {'{{'} o {'}}'}.</span>
              </div>
            )}
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Por qué lo cambias</span>
              <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Queda en la auditoría" />
            </label>
          </aside>
        </div>

        <DialogFooter className="flex-row items-center gap-2 border-t px-6 py-4 sm:justify-between">
          <span className="text-xs text-muted-foreground">{problem}</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button
              disabled={!!problem || save.isPending}
              onClick={() =>
                save.mutate(
                  { name: prompt.name, text, reason: reason.trim() },
                  {
                    onSuccess: () => {
                      toast.success('Borrador guardado. Pruébalo en una evaluación antes de publicarlo.')
                      onClose()
                    },
                    onError: (e) => toast.error(errorDetail(e)),
                  },
                )
              }
            >
              {save.isPending && <Loader2 className="size-4 animate-spin" />} Guardar borrador
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
