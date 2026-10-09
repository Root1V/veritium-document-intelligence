// The page a person opens from the link to upload their documents
// (VRT-47): no account, phone first. Each file is checked in seconds and
// answered in plain words, so a blurry photo is taken again right away.
// The token travels in the link's '#', never to a server in a URL.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { CheckCircle2, CircleAlert, CircleX, FileUp, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Check {
  code: string
  level: 'ok' | 'warning' | 'reject'
  message: string
}

interface UploadedFile {
  id: string
  filename: string
  requirement_key: string | null
  detected_type: string | null
  detected_type_name: string | null
  page_count: number
  checks: Check[]
  verdict: 'ok' | 'warning' | 'reject'
}

interface Session {
  id: string
  process_name: string
  external_ref: string | null
  status: 'open' | 'submitted' | 'expired'
  expires_at: string
  requirements: { key: string; label: string; document_types: string[]; required: boolean; covered: boolean }[]
  files: UploadedFile[]
  submitted_case_id: string | null
  max_file_mb: number
}

type Problem = { title: string; text: string }

async function call<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1/upload-sessions/${path}`, { ...init, headers: { 'X-Upload-Token': token, ...(init.headers ?? {}) } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw Object.assign(new Error(typeof body.detail === 'string' ? body.detail : 'No se pudo completar'), { status: response.status })
  }
  return response.json()
}

const VERDICT = {
  ok: { icon: CheckCircle2, color: 'text-emerald-600', border: 'border-emerald-500/40' },
  warning: { icon: CircleAlert, color: 'text-amber-600', border: 'border-amber-500/50' },
  reject: { icon: CircleX, color: 'text-red-600', border: 'border-red-500/50' },
} as const

function Picker({ label, busy, onFile, variant = 'outline' }: { label: string; busy: boolean; onFile: (f: File) => void; variant?: 'outline' | 'default' }) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="image/*,application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onFile(file)
          e.target.value = ''
        }}
      />
      <Button size="sm" variant={variant} disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <FileUp className="size-4" />}
        {busy ? 'Revisando…' : label}
      </Button>
    </>
  )
}

export function UploadSessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const token = new URLSearchParams(window.location.hash.slice(1)).get('t') ?? ''
  const [session, setSession] = useState<Session | null>(null)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [busy, setBusy] = useState<string | null>(null) // requirement key, 'other' or 'send'
  const [notice, setNotice] = useState<string | null>(null)
  const [sent, setSent] = useState<{ reference: string; files: number } | null>(null)

  const fail = useCallback((error: unknown) => {
    const status = (error as { status?: number }).status
    if (status === 404) setProblem({ title: 'El enlace no es válido', text: 'Revisa que hayas abierto el enlace completo que te enviaron.' })
    else if (status === 410) setProblem({ title: 'El enlace venció', text: 'Pide un enlace nuevo a quien te lo envió.' })
    else setNotice((error as Error).message)
  }, [])

  const invalidLink = !sessionId || !token
  const load = useCallback(() => {
    if (!sessionId || !token) return
    call<Session>(token, sessionId).then(setSession).catch(fail)
  }, [sessionId, token, fail])

  useEffect(load, [load])

  async function upload(file: File, requirementKey: string | null) {
    if (!session) return
    if (file.size > session.max_file_mb * 1024 * 1024) {
      setNotice(`El archivo pesa más de ${session.max_file_mb} MB. Prueba con una foto o un PDF más liviano.`)
      return
    }
    setBusy(requirementKey ?? 'other')
    setNotice(null)
    const form = new FormData()
    form.append('file', file)
    if (requirementKey) form.append('requirement_key', requirementKey)
    try {
      await call<UploadedFile>(token, `${session.id}/files`, { method: 'POST', body: form })
      load()
    } catch (error) {
      fail(error)
    } finally {
      setBusy(null)
    }
  }

  async function remove(fileId: string) {
    if (!session) return
    try {
      setSession(await call<Session>(token, `${session.id}/files/${fileId}`, { method: 'DELETE' }))
    } catch (error) {
      fail(error)
    }
  }

  async function send() {
    if (!session) return
    setBusy('send')
    try {
      setSent(await call<{ reference: string; files: number }>(token, `${session.id}/submit`, { method: 'POST' }))
    } catch (error) {
      fail(error)
    } finally {
      setBusy(null)
    }
  }

  const shell = (children: React.ReactNode) => <div className="mx-auto flex min-h-svh max-w-xl flex-col gap-5 bg-background px-4 py-6">{children}</div>

  const shown = invalidLink ? { title: 'El enlace no es válido', text: 'Revisa que hayas abierto el enlace completo que te enviaron.' } : problem
  if (shown)
    return shell(
      <div className="flex flex-col gap-2 pt-10 text-center">
        <h1 className="text-xl font-semibold">{shown.title}</h1>
        <p className="text-muted-foreground">{shown.text}</p>
      </div>,
    )
  if (!session) return shell(<Loader2 className="mx-auto mt-10 size-6 animate-spin text-muted-foreground" />)
  if (sent || session.status === 'submitted')
    return shell(
      <div className="flex flex-col items-center gap-3 pt-10 text-center">
        <CheckCircle2 className="size-12 text-emerald-600" />
        <h1 className="text-xl font-semibold">¡Listo! Recibimos tus documentos</h1>
        {sent && (
          <p className="text-muted-foreground">
            Enviaste {sent.files} {sent.files === 1 ? 'documento' : 'documentos'}. Tu número de referencia es <strong>{sent.reference}</strong>.
          </p>
        )}
        <p className="text-muted-foreground">Ya puedes cerrar esta página.</p>
      </div>,
    )

  const usable = session.files.filter((f) => f.verdict !== 'reject')
  const missing = session.requirements.filter((r) => r.required && !r.covered)
  // A file goes under the requirement it was uploaded for, or else the first one its type covers.
  const home = (f: UploadedFile) =>
    session.requirements.find((r) => r.key === f.requirement_key)?.key ??
    session.requirements.find((r) => f.detected_type && r.document_types.includes(f.detected_type))?.key ??
    null
  const filesFor = (key: string) => session.files.filter((f) => home(f) === key)
  const other = session.files.filter((f) => home(f) === null)

  const fileCard = (f: UploadedFile) => {
    const v = VERDICT[f.verdict]
    return (
      <div key={f.id} className={cn('flex flex-col gap-1 rounded-md border p-3 text-sm', v.border)}>
        <div className="flex items-center gap-2">
          <v.icon className={cn('size-5 shrink-0', v.color)} />
          <span className="truncate font-medium">{f.filename}</span>
          <button type="button" className="ml-auto text-xs text-muted-foreground underline" onClick={() => remove(f.id)}>
            Quitar
          </button>
        </div>
        {f.checks.map((c) => (
          <span key={c.code} className={c.level === 'ok' ? 'text-muted-foreground' : ''}>
            {c.message}
          </span>
        ))}
        {f.detected_type_name && <span className="text-xs text-muted-foreground">Reconocido como: {f.detected_type_name}</span>}
        {f.verdict === 'reject' && <span className="text-xs text-muted-foreground">Este archivo no se enviará.</span>}
      </div>
    )
  }

  return shell(
    <>
      <div>
        <p className="text-sm text-muted-foreground">{session.process_name}</p>
        <h1 className="text-2xl font-semibold tracking-tight">Sube tus documentos</h1>
        <p className="text-sm text-muted-foreground">
          Puedes tomar una foto con el teléfono o subir un PDF. Revisamos cada uno al momento. El enlace vence a las{' '}
          {new Date(session.expires_at).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' }).replace(/\.$/, '')}.
        </p>
      </div>

      {notice && <div className="rounded-md border border-amber-500/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">{notice}</div>}

      <div className="flex flex-col gap-4">
        {session.requirements.map((r) => (
          <div key={r.key} className="flex flex-col gap-2 rounded-lg border p-3">
            <div className="flex items-center gap-2">
              {r.covered ? <CheckCircle2 className="size-5 shrink-0 text-emerald-600" /> : <span className="size-5 shrink-0 rounded-full border-2" />}
              <span className="font-medium">{r.label}</span>
              {!r.required && <span className="text-xs text-muted-foreground">(si aplica)</span>}
            </div>
            {filesFor(r.key).map(fileCard)}
            <div>
              <Picker label={filesFor(r.key).length ? 'Subir otra' : 'Subir'} busy={busy === r.key} onFile={(f) => upload(f, r.key)} />
            </div>
          </div>
        ))}
        <div className="flex flex-col gap-2 rounded-lg border border-dashed p-3">
          <span className="font-medium">Otro documento</span>
          {other.map(fileCard)}
          <div>
            <Picker label="Subir" busy={busy === 'other'} onFile={(f) => upload(f, null)} />
          </div>
        </div>
      </div>

      <div className="sticky bottom-0 flex flex-col gap-2 border-t bg-background py-3">
        {missing.length > 0 && usable.length > 0 && (
          <span className="text-xs text-muted-foreground">Aún falta: {missing.map((r) => r.label).join(', ')}.</span>
        )}
        <Button disabled={!usable.length || busy !== null} onClick={send}>
          {busy === 'send' && <Loader2 className="size-4 animate-spin" />} Enviar {usable.length || ''} {usable.length === 1 ? 'documento' : 'documentos'}
        </Button>
      </div>
    </>,
  )
}
