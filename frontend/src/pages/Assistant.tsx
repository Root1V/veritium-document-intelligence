// The user's assistant (VRT-54): questions about the cases, answered by an
// agent that consults Veritium with the person's own permissions. It only
// reads; actions stay on the case's page. The conversation lives here and is
// sent whole with each question.
import { Fragment, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Bot, Loader2, RotateCcw, Send } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { errorDetail } from '@/lib/apiErrors'
import { useAskAssistant, useCaseResult } from '@/lib/queries'
import type { AssistantReply, AssistantTurn } from '@/types/api'

type Message = AssistantTurn & { reply?: AssistantReply }

const EXAMPLES = [
  '¿Qué expedientes llegaron hoy y cómo van?',
  '¿Por qué el expediente EXP-A2A-001 está en revisión humana?',
  '¿Qué documentos pide el proceso de convenios?',
]
const ABOUT_CASE = ['¿Por qué tiene este veredicto?', '¿Qué le falta?', '¿De dónde sale el ingreso del titular?']

// The model may still mark emphasis with **…**: shown as bold, never as asterisks.
function Text({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap">
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : <Fragment key={i}>{part}</Fragment>))}
    </p>
  )
}

export function AssistantPage() {
  const [params] = useSearchParams()
  const caseId = params.get('case') ?? undefined
  const { data: about } = useCaseResult(caseId)
  const ask = useAskAssistant()
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [failed, setFailed] = useState<string | null>(null)

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
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            <CardTitle className="flex items-center gap-2">
              <Bot className="size-5" /> Asistente
            </CardTitle>
            <CardDescription>
              Pregúntale por los expedientes: en qué etapa van, por qué tienen su veredicto, qué les falta y de dónde sale un dato. Consulta
              con tus mismos permisos y no cambia nada.
              {caseName && (
                <>
                  {' '}
                  Ahora conversas sobre el expediente{' '}
                  <Link to={`/cases/${caseId}`} className="underline">
                    {caseName}
                  </Link>
                  .
                </>
              )}
            </CardDescription>
          </div>
          {messages.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setMessages([])} disabled={ask.isPending}>
              <RotateCcw className="size-3.5" /> Nueva conversación
            </Button>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {messages.length === 0 && (
            <div className="flex flex-wrap gap-2">
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
                  <div className="flex flex-wrap gap-2">
                    {m.reply.cases.map((c) => (
                      <Link key={c.id} to={`/cases/${c.id}`}>
                        <Badge variant="outline" className="hover:bg-accent">
                          Ver expediente {c.label}
                        </Badge>
                      </Link>
                    ))}
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
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              send(draft)
            }}
          >
            <Textarea
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
            <Button type="submit" disabled={ask.isPending || !draft.trim()}>
              <Send className="size-4" /> Enviar
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
