// Opens an upload session (VRT-47) and gives the link to send to the
// person whose documents they are: they upload from their phone, get each
// file checked in seconds, and send — the case is created then.
import { useState } from 'react'
import { Copy, Link2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorDetail } from '@/lib/apiErrors'
import { useOpenUploadSession, useProcessProfiles } from '@/lib/queries'

export function UploadLinkDialog() {
  const { data: profiles } = useProcessProfiles()
  const open = useOpenUploadSession()
  const [profile, setProfile] = useState('')
  const [reference, setReference] = useState('')
  const [link, setLink] = useState<{ url: string; expires: string } | null>(null)

  return (
    <Dialog onOpenChange={(o) => !o && setLink(null)}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Link2 className="size-4" /> Enlace de carga
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Pedir documentos con un enlace</DialogTitle>
        </DialogHeader>
        {link ? (
          <div className="flex flex-col gap-3 text-sm">
            <p>Envía este enlace a la persona. Podrá subir sus documentos desde el teléfono y verá al momento si cada uno se puede leer.</p>
            <Input readOnly value={link.url} onFocus={(e) => e.target.select()} className="text-xs" />
            <div className="flex gap-2">
              <Button size="sm" onClick={() => navigator.clipboard.writeText(link.url).then(() => toast.success('Enlace copiado.'))}>
                <Copy className="size-3.5" /> Copiar
              </Button>
              <Button size="sm" variant="outline" asChild>
                <a href={link.url} target="_blank" rel="noreferrer">
                  Abrir
                </a>
              </Button>
            </div>
            <span className="text-xs text-muted-foreground">Vence el {new Date(link.expires).toLocaleString('es-PE')}. Cuando la persona envíe, el expediente aparecerá en la lista.</span>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <Select value={profile} onValueChange={setProfile}>
              <SelectTrigger>
                <SelectValue placeholder="Proceso" />
              </SelectTrigger>
              <SelectContent>
                {(profiles ?? []).map((p) => (
                  <SelectItem key={p.key} value={p.key}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input placeholder="Referencia del expediente (opcional)" value={reference} onChange={(e) => setReference(e.target.value)} />
            <Button
              disabled={!profile || open.isPending}
              onClick={() =>
                open.mutate(
                  { profile, external_ref: reference.trim() || undefined },
                  { onSuccess: (s) => setLink({ url: s.upload_url, expires: s.expires_at }), onError: (e) => toast.error(errorDetail(e)) },
                )
              }
            >
              {open.isPending && <Loader2 className="size-4 animate-spin" />} Crear enlace
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
