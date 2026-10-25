// The user's assistant (VRT-54): questions about the cases, answered by an
// agent that consults Veritium with the person's own permissions. It only
// reads; actions stay on the case's page. A panel docked to the right of every
// page (⌘K / Ctrl K), so the conversation survives navigation; on a case's page
// it talks about that case unless the person drops it. The conversation is
// sent whole with each question.
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, matchPath, useLocation } from 'react-router-dom'
import { ArrowUp, ArrowUpRight, Copy, FolderOpen, PanelRightClose, RotateCcw, Sparkles, SquarePen, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { errorDetail } from '@/lib/apiErrors'
import { AssistantContext } from '@/lib/assistant'
import { getUserName, isAuthenticated } from '@/lib/auth'
import { useAskAssistant, useCaseResult } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { AssistantReply, AssistantTurn } from '@/types/api'

type Message = AssistantTurn & { reply?: AssistantReply }

const GENERAL = [
  '¿Qué expedientes llegaron hoy y cómo van?',
  '¿Cuántos expedientes se devolvieron al cliente esta semana?',
  '¿Qué tengo pendiente en la cola de revisión?',
  '¿Qué documentos pide el proceso de convenios?',
]
const ON_REVIEW = ['¿Qué tengo pendiente en la cola de revisión?', '¿Qué expedientes esperan una revisión humana?', '¿Qué expedientes llegaron hoy y cómo van?']
const ABOUT_CASE = ['¿Por qué tiene este veredicto?', '¿Qué le falta?', '¿De dónde sale el ingreso del titular?']
const MAX_LINKS = 6
const PUBLIC_PATHS = ['/login', '/carga/:sessionId']
const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent)
const SHORTCUT = MAC ? '⌘K' : 'Ctrl K'

// The model may still mark emphasis with **…**: shown as bold, never as asterisks.
function Text({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap leading-relaxed">
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : <Fragment key={i}>{part}</Fragment>))}
    </p>
  )
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const pageCase = matchPath('/cases/:id', pathname)?.params.id
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  // A conversation stays on the case it started with, until a new one.
  const [conversationCase, setConversationCase] = useState<string | undefined>()
  const [dropped, setDropped] = useState<string | undefined>()
  const caseId = messages.length > 0 ? conversationCase : pageCase !== dropped ? pageCase : undefined
  const hidden = !isAuthenticated() || PUBLIC_PATHS.some((p) => matchPath(p, pathname))

  useEffect(() => {
    if (hidden) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [hidden])

  function openFor(id: string) {
    if (messages.length > 0 && conversationCase !== id) setMessages([])
    setDropped(undefined)
    setOpen(true)
  }

  return (
    <AssistantContext.Provider value={{ open: open && !hidden, openFor }}>
      {children}
      {!hidden &&
        (open ? (
          <Panel
            caseId={caseId}
            canDrop={messages.length === 0 && !!caseId}
            onDrop={() => setDropped(pageCase)}
            examples={caseId ? ABOUT_CASE : pathname.startsWith('/review') ? ON_REVIEW : GENERAL}
            messages={messages}
            setMessages={(next) => {
              if (messages.length === 0) setConversationCase(caseId)
              setMessages(next)
            }}
            onClose={() => setOpen(false)}
          />
        ) : (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="fixed right-6 bottom-6 z-40 flex items-center gap-2 rounded-full bg-primary py-2.5 pr-2.5 pl-4 text-sm font-medium text-primary-foreground shadow-lg transition hover:shadow-xl hover:brightness-110"
          >
            <Sparkles className="size-4" /> Preguntar
            <kbd className="rounded-md bg-primary-foreground/20 px-1.5 py-0.5 font-sans text-xs">{SHORTCUT}</kbd>
          </button>
        ))}
    </AssistantContext.Provider>
  )
}

function Panel({
  caseId,
  canDrop,
  onDrop,
  examples,
  messages,
  setMessages,
  onClose,
}: {
  caseId?: string
  canDrop: boolean
  onDrop: () => void
  examples: string[]
  messages: Message[]
  setMessages: (messages: Message[]) => void
  onClose: () => void
}) {
  const { data: about } = useCaseResult(caseId)
  const ask = useAskAssistant()
  const [draft, setDraft] = useState('')
  const [failed, setFailed] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)
  const firstName = getUserName()?.split(' ')[0]

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [messages.length, ask.isPending, failed])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function send(question: string) {
    const text = question.trim()
    if (!text || ask.isPending) return
    const conversation: Message[] = [...messages, { role: 'user', text }]
    setMessages(conversation)
    setDraft('')
    setFailed(null)
    ask.mutate(
      { conversation: conversation.map(({ role, text }) => ({ role, text })), case_id: caseId },
      {
        onSuccess: (reply) => setMessages([...conversation, { role: 'assistant', text: reply.answer, reply }]),
        onError: (e) => {
          setMessages(messages) // the question goes back to the box, to send again
          setDraft(text)
          setFailed(errorDetail(e))
        },
      },
    )
    box.current?.focus()
  }

  function startOver() {
    setMessages([])
    setFailed(null)
    box.current?.focus()
  }

  const caseName = about ? (about.case.external_ref ?? about.case.id.slice(0, 8)) : null

  return (
    <aside
      aria-label="Asistente"
      className="fixed inset-0 z-50 flex flex-col bg-background duration-200 animate-in slide-in-from-right sm:left-auto sm:w-[420px] sm:border-l sm:shadow-2xl"
    >
      <header className="flex items-start gap-3 border-b px-4 py-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Sparkles className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">Asistente</h2>
          <p className="text-xs text-muted-foreground">Responde con lo que Veritium tiene ahora, con tus permisos. No cambia nada.</p>
        </div>
        <Button variant="ghost" size="icon" className="size-8" onClick={startOver} disabled={messages.length === 0 || ask.isPending} title="Nueva conversación">
          <SquarePen className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-8" onClick={onClose} title="Cerrar (Esc)">
          <PanelRightClose className="size-4" />
        </Button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 py-4">
        {messages.length === 0 && (
          <div className="mt-auto flex flex-col gap-4">
            <div>
              <p className="text-lg font-semibold">{firstName ? `Hola, ${firstName}.` : 'Hola.'}</p>
              <p className="text-sm text-muted-foreground">
                {caseName ? `¿Qué quieres saber del expediente ${caseName}?` : 'Pregúntame por los expedientes: cómo van, por qué tienen su veredicto, qué les falta y de dónde sale un dato.'}
              </p>
            </div>
            <div className="flex flex-col gap-2">
              {examples.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => send(q)}
                  className="group flex items-center justify-between gap-2 rounded-lg border px-3 py-2.5 text-left text-sm transition hover:border-primary/40 hover:bg-primary/5"
                >
                  {q}
                  <ArrowUp className="size-3.5 shrink-0 rotate-45 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.length > 0 && caseName && (
          <p className="text-center text-xs text-muted-foreground">
            Conversación sobre el expediente{' '}
            <Link to={`/cases/${caseId}`} className="underline">
              {caseName}
            </Link>
          </p>
        )}

        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm text-primary-foreground">
              <Text text={m.text} />
            </div>
          ) : (
            <div key={i} className="group flex gap-2.5">
              <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                <Sparkles className="size-3.5" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-2 text-sm">
                <Text text={m.text} />
                {m.reply && m.reply.cases.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.reply.cases.slice(0, MAX_LINKS).map((c) => (
                      <Link
                        key={c.id}
                        to={`/cases/${c.id}`}
                        className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition hover:border-primary/40 hover:bg-primary/5"
                      >
                        {c.label} <ArrowUpRight className="size-3" />
                      </Link>
                    ))}
                    {m.reply.cases.length > MAX_LINKS && (
                      <Link to="/cases" className="self-center text-xs text-muted-foreground underline">
                        y {m.reply.cases.length - MAX_LINKS} más
                      </Link>
                    )}
                  </div>
                )}
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:text-foreground"
                    onClick={() => navigator.clipboard.writeText(m.text).then(() => toast.success('Respuesta copiada'))}
                  >
                    <Copy className="size-3" /> Copiar
                  </button>
                  {m.reply && m.reply.consulted.length > 0 && (
                    <details>
                      <summary className="cursor-pointer hover:text-foreground">Qué consultó</summary>
                      <p className="mt-1">{m.reply.consulted.join(' → ')}</p>
                    </details>
                  )}
                </div>
              </div>
            </div>
          ),
        )}

        {ask.isPending && (
          <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
            <span className="flex size-6 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Sparkles className="size-3.5 animate-pulse" />
            </span>
            Consultando
            <span className="flex gap-0.5">
              {[0, 150, 300].map((d) => (
                <span key={d} className="size-1 animate-bounce rounded-full bg-current" style={{ animationDelay: `${d}ms` }} />
              ))}
            </span>
          </div>
        )}
        {failed && (
          <div className="flex items-start justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            <span>No pude responder: {failed}</span>
            <Button variant="ghost" size="sm" className="h-7 shrink-0" onClick={() => send(draft)}>
              <RotateCcw className="size-3.5" /> Reintentar
            </Button>
          </div>
        )}
        <div ref={end} />
      </div>

      <form
        className="border-t px-4 pt-3 pb-2"
        onSubmit={(e) => {
          e.preventDefault()
          send(draft)
        }}
      >
        <div className="flex flex-col gap-2 rounded-xl border bg-background p-2 transition focus-within:border-primary/50 focus-within:ring-3 focus-within:ring-primary/10">
          {canDrop && caseName && (
            <span className="inline-flex w-fit items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs">
              <FolderOpen className="size-3.5" /> Expediente {caseName}
              <button type="button" onClick={onDrop} className="text-muted-foreground hover:text-foreground" title="Preguntar en general">
                <X className="size-3" />
              </button>
            </span>
          )}
          <div className="flex items-end gap-2">
            <textarea
              ref={box}
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(draft)
                }
              }}
              placeholder={caseName && canDrop ? 'Pregunta sobre este expediente…' : 'Escribe tu pregunta…'}
              rows={1}
              maxLength={4000}
              disabled={ask.isPending}
              className="field-sizing-content max-h-40 min-h-9 flex-1 resize-none bg-transparent px-1.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
            />
            <Button type="submit" size="icon" className={cn('size-8 shrink-0 rounded-lg', !draft.trim() && 'opacity-40')} disabled={ask.isPending || !draft.trim()} aria-label="Enviar">
              <ArrowUp className="size-4" />
            </Button>
          </div>
        </div>
        <p className="mt-1.5 text-center text-[11px] text-muted-foreground">Enter para enviar · Shift+Enter, nueva línea · Esc para cerrar</p>
      </form>
    </aside>
  )
}
