// Running a suite (VRT-42, VRT-107): with the configuration in use, or
// trying something before publishing it — the business meaning of each
// field, the self-check of the draft, or a draft of an instruction.
import { useState } from 'react'
import { Loader2, Play } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { errorDetail } from '@/lib/apiErrors'
import { usePrompts, useRunEvalSuite } from '@/lib/queries'
import type { EvalRunSummary } from '@/types/api'

function Option({ checked, onChange, title, hint }: { checked: boolean; onChange: (v: boolean) => void; title: string; hint: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition hover:border-primary/40 has-[:checked]:border-primary has-[:checked]:bg-primary/5">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-1" />
      <span className="flex flex-col">
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </span>
    </label>
  )
}

export function RunDialog({ suiteId, onClose, onStarted }: { suiteId: string; onClose: () => void; onStarted: (run: EvalRunSummary) => void }) {
  const run = useRunEvalSuite()
  const { data: prompts } = usePrompts()
  const drafts = (prompts ?? []).filter((p) => p.draft)
  const [meaning, setMeaning] = useState(false)
  const [selfCheck, setSelfCheck] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const trying = meaning || selfCheck || chosen.length > 0

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>Correr el conjunto</DialogTitle>
          <DialogDescription>Con la configuración en uso, o probando algo antes de publicarlo. Nada de esto cambia lo que se procesa.</DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-6 py-5">
          <span className="text-sm font-medium">Probar además (opcional)</span>
          <Option checked={meaning} onChange={setMeaning} title="El significado de negocio de cada campo" hint="Se le dice al modelo qué significa cada dato, según el catálogo de datos." />
          <Option checked={selfCheck} onChange={setSelfCheck} title="La autovalidación del borrador" hint="El modelo revisa lo que leyó con las reglas del documento y corrige antes de entregar." />
          {drafts.map((p) => (
            <Option
              key={p.draft!.id}
              checked={chosen.includes(p.draft!.id)}
              onChange={(on) => setChosen((c) => (on ? [...c, p.draft!.id] : c.filter((id) => id !== p.draft!.id)))}
              title={`El borrador de «${p.label}»`}
              hint={p.draft!.reason}
            />
          ))}
        </div>
        <DialogFooter className="flex-row items-center gap-2 border-t px-6 py-4 sm:justify-end">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            disabled={run.isPending}
            onClick={() =>
              run.mutate(
                { suiteId, semanticGrounding: meaning || undefined, promptDrafts: chosen, selfCheck },
                {
                  onSuccess: (r) => (toast.success('Corrida en curso.'), onStarted(r)),
                  onError: (e) => toast.error(errorDetail(e)),
                },
              )
            }
          >
            {run.isPending ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} {trying ? 'Correr con lo elegido' : 'Correr con la configuración en uso'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
