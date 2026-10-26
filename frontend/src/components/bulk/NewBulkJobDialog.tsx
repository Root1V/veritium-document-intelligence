// A new bulk job (VRT-48, VRT-109) in three numbered steps — prepare the ZIP,
// choose the process, send it — and what was received, with what will not be
// processed and why, before leaving.
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Download, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorDetail } from '@/lib/apiErrors'
import { downloadFile, useProcessProfiles, useSubmitBulkJob } from '@/lib/queries'

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

export function NewBulkJobDialog({ onClose }: { onClose: () => void }) {
  const submit = useSubmitBulkJob()
  const { data: profiles } = useProcessProfiles()
  const [profile, setProfile] = useState('')
  const [name, setName] = useState('')
  const [archive, setArchive] = useState<File | null>(null)
  const published = (profiles ?? []).filter((p) => p.active_version !== null)
  const result = submit.data
  const problem = !profile ? 'Elige el proceso.' : !archive ? 'Falta el archivo ZIP.' : null

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>{result ? 'Carga recibida' : 'Nueva carga masiva'}</DialogTitle>
          <DialogDescription>
            {result ? 'Sus expedientes avanzan de a pocos para no retrasar las solicitudes en línea.' : 'Muchos expedientes de una vez, en un archivo ZIP.'}
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5 text-sm">
          {result ? (
            <div className="flex flex-col gap-2">
              <p>
                Se recibieron <strong>{result.cases}</strong> expedientes.
              </p>
              {result.skipped.length > 0 && (
                <div className="rounded-lg bg-amber-500/10 px-3 py-2 text-amber-800 dark:text-amber-300">
                  <span className="font-medium">No se procesarán {result.skipped.length}:</span>
                  <ul className="mt-1 list-disc pl-5">
                    {result.skipped.map((s, i) => (
                      <li key={i}>{s.reference ? `${s.reference}: ${s.reason}` : s.reason}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <>
              <Step n={1} title="Prepara el ZIP">
                <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                  <li>
                    Una carpeta por expediente, con su referencia como nombre (p. ej. <code>EXP-0001</code>).
                  </li>
                  <li>Dentro, los documentos de ese expediente (PDF o fotos).</li>
                  <li>Opcional: un manifiesto (Excel o CSV) para dar a un expediente otro proceso o sus datos.</li>
                </ul>
              </Step>
              <Step n={2} title="Elige el proceso">
                <div className="flex flex-wrap gap-2">
                  <Select value={profile} onValueChange={setProfile}>
                    <SelectTrigger className="w-64">
                      <SelectValue placeholder="Proceso" />
                    </SelectTrigger>
                    <SelectContent>
                      {published.map((p) => (
                        <SelectItem key={p.key} value={p.key}>
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {profile && (
                    <Button
                      variant="ghost"
                      onClick={() => downloadFile('/v1/bulk-jobs/template', { profile }, 'manifiesto.csv').catch((e) => toast.error(errorDetail(e)))}
                    >
                      <Download className="size-4" /> Manifiesto de ejemplo
                    </Button>
                  )}
                </div>
              </Step>
              <Step n={3} title="Envía el ZIP">
                <Input placeholder="Nombre de la carga (opcional), p. ej. Convenios octubre" value={name} onChange={(e) => setName(e.target.value)} />
                <Input type="file" accept=".zip,application/zip" onChange={(e) => setArchive(e.target.files?.[0] ?? null)} />
              </Step>
            </>
          )}
        </div>

        <DialogFooter className="flex-row items-center gap-2 border-t px-6 py-4 sm:justify-between">
          {result ? (
            <>
              <span />
              <div className="flex gap-2">
                <Button variant="ghost" onClick={onClose}>
                  Cerrar
                </Button>
                <Button asChild>
                  <Link to={`/bulk/${result.id}`}>Ver su avance</Link>
                </Button>
              </div>
            </>
          ) : (
            <>
              <span className="text-xs text-muted-foreground">{problem}</span>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={onClose}>
                  Cancelar
                </Button>
                <Button
                  disabled={!!problem || submit.isPending}
                  onClick={() => archive && submit.mutate({ archive, profile, name: name.trim() }, { onError: (e) => toast.error(errorDetail(e)) })}
                >
                  {submit.isPending && <Loader2 className="size-4 animate-spin" />} Enviar carga
                </Button>
              </div>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
