// A new evaluation suite (VRT-42, VRT-107): choose the way first — the
// human corrections, in one step, or a table of expected values, in three
// numbered steps — instead of two forms side by side on the page.
import { useState, type ReactNode } from 'react'
import { ClipboardCheck, Download, Loader2, Table2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorDetail } from '@/lib/apiErrors'
import { downloadFile, useCreateEvalSuite, useCreateGoldenSet, useDocumentTypeCatalog } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { EvalSuiteDetail } from '@/types/api'

type Way = 'corrections' | 'table'

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">{n}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <span className="text-sm font-medium">{title}</span>
        {children}
      </div>
    </div>
  )
}

export function NewSuiteDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (suite: EvalSuiteDetail) => void }) {
  const fromCorrections = useCreateGoldenSet()
  const fromTable = useCreateEvalSuite()
  const { data: types } = useDocumentTypeCatalog()
  const [way, setWay] = useState<Way>('corrections')
  const [name, setName] = useState('')
  const [templateType, setTemplateType] = useState('')
  const [table, setTable] = useState<File | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const pending = fromCorrections.isPending || fromTable.isPending
  const problem =
    name.trim().length < 3 ? 'Ponle un nombre (mínimo 3 letras).' : way === 'table' && !table ? 'Falta la tabla.' : way === 'table' && !files.length ? 'Faltan los documentos.' : null

  const done = { onSuccess: (s: EvalSuiteDetail) => (toast.success(`Conjunto creado con ${s.case_count} documentos.`), onCreated(s)), onError: (e: unknown) => toast.error(errorDetail(e)) }
  const create = () =>
    way === 'corrections' ? fromCorrections.mutate({ name: name.trim() }, done) : table && fromTable.mutate({ name: name.trim(), description: '', table, files }, done)

  const WAYS: { key: Way; icon: typeof Table2; title: string; hint: string }[] = [
    { key: 'corrections', icon: ClipboardCheck, title: 'Desde las correcciones', hint: 'Los documentos que un revisor corrigió, con los valores que dejó. Mide justo donde la lectura se equivocó antes.' },
    { key: 'table', icon: Table2, title: 'Desde una tabla', hint: 'Tus documentos y, en una tabla, lo que debería leerse de cada uno.' },
  ]

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>Nuevo conjunto de prueba</DialogTitle>
          <DialogDescription>Documentos cuya respuesta correcta ya se conoce, para medir la lectura antes de publicar un cambio.</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          <div className="grid gap-2 sm:grid-cols-2">
            {WAYS.map((w) => (
              <button
                key={w.key}
                type="button"
                onClick={() => setWay(w.key)}
                className={cn('flex flex-col gap-1 rounded-lg border p-3 text-left transition', way === w.key ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:border-primary/40')}
              >
                <span className="inline-flex items-center gap-2 text-sm font-medium">
                  <w.icon className="size-4 text-primary" /> {w.title}
                </span>
                <span className="text-xs text-muted-foreground">{w.hint}</span>
              </button>
            ))}
          </div>

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Nombre del conjunto</span>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="p. ej. Boletas de octubre" autoFocus />
          </label>

          {way === 'table' && (
            <div className="flex flex-col gap-4">
              <Step n={1} title="Descarga la plantilla del tipo de documento">
                <div className="flex flex-wrap gap-2">
                  <Select value={templateType} onValueChange={setTemplateType}>
                    <SelectTrigger className="w-60">
                      <SelectValue placeholder="Tipo de documento" />
                    </SelectTrigger>
                    <SelectContent>
                      {(types?.registered ?? []).map((t) => (
                        <SelectItem key={t.name} value={t.name}>
                          {t.display_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    disabled={!templateType}
                    onClick={() => downloadFile('/v1/eval-suites/template', { document_type: templateType }, 'evaluacion.csv').catch((e) => toast.error(errorDetail(e)))}
                  >
                    <Download className="size-4" /> Descargar
                  </Button>
                </div>
              </Step>
              <Step n={2} title="Llénala: una fila por documento">
                <span className="text-xs text-muted-foreground">
                  El nombre del archivo, su tipo, las páginas si es parte de un archivo mayor (p. ej. 1-2) y el valor correcto de cada dato. Una celda vacía no se mide.
                  Reemplaza la fila de ejemplo.
                </span>
              </Step>
              <Step n={3} title="Sube la tabla y los documentos que nombra">
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Tabla (.csv o .xlsx)</span>
                  <Input type="file" accept=".csv,.xlsx" onChange={(e) => setTable(e.target.files?.[0] ?? null)} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Documentos{files.length > 0 && ` · ${files.length} elegidos`}</span>
                  <Input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
                </label>
              </Step>
            </div>
          )}
        </div>

        <DialogFooter className="flex-row items-center gap-2 border-t px-6 py-4 sm:justify-between">
          <span className="text-xs text-muted-foreground">{problem}</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button disabled={!!problem || pending} onClick={create}>
              {pending && <Loader2 className="size-4 animate-spin" />} Crear conjunto
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
