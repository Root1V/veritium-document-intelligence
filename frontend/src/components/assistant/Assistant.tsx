// The user's assistant (VRT-54): questions about the cases, answered by an
// agent that consults Veritium with the person's own permissions. It only
// reads; actions stay on the case's page. It floats over every page, so the
// conversation survives navigation; on a case's page it talks about that case.
// The conversation is sent whole with each question.
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, matchPath, useLocation } from 'react-router-dom'
import { Bot, Loader2, RotateCcw, Send, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { errorDetail } from '@/lib/apiErrors'
import { AssistantContext } from '@/lib/assistant'
import { isAuthenticated } from '@/lib/auth'
import { useAskAssistant, useCaseResult } from '@/lib/queries'
import type { AssistantReply, AssistantTurn } from '@/types/api'

type Message = AssistantTurn & { reply?: AssistantReply }

const EXAMPLES = [
  '¿Qué expedientes llegaron hoy y cómo van?',
  '¿Cuántos expedientes se devolvieron al cliente esta semana?',
  '¿Qué tengo pendiente en la cola de revisión?',
  '¿Qué documentos pide el proceso de convenios?',
]
const MAX_LINKS = 6
const ABOUT_CASE = ['¿Por qué tiene este veredicto?', '¿Qué le falta?', '¿De dónde sale el ingreso del titular?']
const PUBLIC_PATHS = ['/login', '/carga/:sessionId']

// The model may still mark emphasis with **…**: shown as bold, never as asterisks.
function Text({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap">
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
  const caseId = messages.length > 0 ? conversationCase : pageCase
  const hidden = !isAuthenticated() || PUBLIC_PATHS.some((p) => matchPath(p, pathname))

  function openFor(id: string) {
    if (messages.length > 0 && conversationCase !== id) setMessages([])
    setOpen(true)
  }

  return (
    <AssistantContext.Provider value={{ openFor }}>
      {children}
      {!hidden && (
        <>
          {open && (
            <Chat
              caseId={caseId}
              messages={messages}
              setMessages={(next) => {
                if (messages.length === 0) setConversationCase(caseId)
                setMessages(next)
              }}
              onClose={() => setOpen(false)}
            />
          )}
          <Button size="lg" className="fixed right-6 bottom-6 z-40 rounded-full shadow-lg" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? <X className="size-5" /> : <Bot className="size-5" />}
            {open ? 'Cerrar' : 'Asistente'}
          </Button>
        </>
      )}
    </AssistantContext.Provider>
  )
}

function Chat({
  caseId,
  messages,
  setMessages,
  onClose,
}: {
  caseId?: string
  messages: Message[]
  setMessages: (messages: Message[]) => void
  onClose: () => void
}) {
  const { data: about } = useCaseResult(caseId)
  const ask = useAskAssistant()
  const [draft, setDraft] = useState('')
  const [failed, setFailed] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, ask.isPending])
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
  }

  const caseName = about ? (about.case.external_ref ?? about.case.id.slice(0, 8)) : null
  const examples = caseId ? ABOUT_CASE : EXAMPLES

  return (
    <section
      aria-label="Asistente"
      className="fixed inset-x-4 bottom-22 z-40 flex max-h-[min(640px,calc(100svh-8rem))] flex-col rounded-xl border bg-background shadow-2xl sm:inset-x-auto sm:right-6 sm:w-[420px]"
    >
      <header className="flex items-start justify-between gap-2 border-b px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <span className="flex items-center gap-2 font-semibold">
            <Bot className="size-4" /> Asistente
          </span>
          <span className="text-xs text-muted-foreground">
            {caseName ? (
              <>
                Sobre el expediente{' '}
                <Link to={`/cases/${caseId}`} className="underline">
                  {caseName}
                </Link>
                .{' '}
              </>
            ) : (
              'Pregúntale por los expedientes. '
            )}
            Consulta con tus permisos y no cambia nada.
          </span>
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => setMessages([])} disabled={ask.isPending}>
            <RotateCcw className="size-3.5" /> Nueva
          </Button>
        )}
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
        {messages.length === 0 && (
          <div className="flex flex-col items-start gap-2">
            {examples.map((q) => (
              <Button key={q} variant="outline" size="sm" className="h-auto whitespace-normal text-left" onClick={() => send(q)}>
                {q}
              </Button>
            ))}
          </div>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="ml-auto max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
              <Text text={m.text} />
            </div>
          ) : (
            <div key={i} className="flex max-w-[95%] flex-col gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm">
              <Text text={m.text} />
              {m.reply && m.reply.cases.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  {m.reply.cases.slice(0, MAX_LINKS).map((c) => (
                    <Link key={c.id} to={`/cases/${c.id}`}>
                      <Badge variant="outline" className="hover:bg-accent">
                        Ver {c.label}
                      </Badge>
                    </Link>
                  ))}
                  {m.reply.cases.length > MAX_LINKS && (
                    <Link to="/cases" className="text-xs text-muted-foreground underline">
                      y {m.reply.cases.length - MAX_LINKS} más en Expedientes
                    </Link>
                  )}
                </div>
              )}
              {m.reply && m.reply.consulted.length > 0 && (
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">Qué consultó</summary>
                  {m.reply.consulted.join(' → ')}
                </details>
              )}
            </div>
          ),
        )}
        {ask.isPending && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Consultando…
          </div>
        )}
        {failed && <p className="text-sm text-destructive">{failed}</p>}
        <div ref={end} />
      </div>

      <form
        className="flex items-end gap-2 border-t px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault()
          send(draft)
        }}
      >
        <Textarea
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(draft)
            }
          }}
          placeholder="Escribe tu pregunta…"
          rows={2}
          maxLength={4000}
          disabled={ask.isPending}
        />
        <Button type="submit" size="icon" disabled={ask.isPending || !draft.trim()} aria-label="Enviar">
          <Send className="size-4" />
        </Button>
      </form>
    </section>
  )
}
