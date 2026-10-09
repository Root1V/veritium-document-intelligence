// The instructions the platform gives the models (VRT-46): what each one is
// for, the version in effect and since when, its text and its earlier
// versions. Opened from a case or an evaluation run, it says which version
// that run used. An AI specialist changes them here under governance
// (VRT-63): a draft with its reason, tried in an evaluation, published, and
// undone in one click; everyone else reads.
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { errorDetail } from '@/lib/apiErrors'
import { isAISpecialist } from '@/lib/auth'
import { percent } from '@/lib/evaluation'
import { cn } from '@/lib/utils'
import { diffLines } from '@/lib/textDiff'
import {
  useCaseResult,
  useDiscardPromptDraft,
  useEvalRun,
  usePrompts,
  usePublishPromptDraft,
  useRestorePrompt,
  useSavePromptDraft,
} from '@/lib/queries'
import type { PromptView } from '@/types/api'

const date = (iso: string | null) => (iso ? new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' }) : '—')

// What the platform fills in, each time, where the text has {…}.
const FILLED: Record<string, string> = {
  hint: 'las pistas del tipo de documento',
  regions: 'las regiones de texto detectadas en el documento',
  schema: 'los campos que hay que extraer',
  grounding: 'el significado de negocio de los campos, si está activado',
  types: 'los tipos de documento registrados',
  known_types: 'los tipos de documento registrados',
  attributes: 'los atributos del catálogo semántico',
  roles: 'los roles del catálogo semántico',
  area: 'el área (Riesgos o Legal)',
  instructions: 'el enfoque que definió el área',
  playbook: 'los puntos del playbook de Legal',
}

function Used({ prompt, used, from }: { prompt: PromptView; used: string | undefined; from: string }) {
  if (!used) return null
  if (used === prompt.version) return <Badge variant="secondary">{from} usó esta versión</Badge>
  const earlier = prompt.earlier.find((e) => e.version === used)
  return (
    <Badge variant="outline" className="border-amber-600 text-amber-700 dark:text-amber-400">
      {from} usó una versión anterior{earlier ? ` (del ${date(earlier.first_seen_at)})` : ''}
    </Badge>
  )
}

function Diff({ before, after }: { before: string; after: string }) {
  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
      {diffLines(before, after)
        .filter((l, i, all) => l.kind !== 'same' || all.slice(Math.max(0, i - 2), i + 3).some((n) => n.kind !== 'same'))
        .map((l, i) => (
          <div key={i} className={cn(l.kind === 'added' && 'bg-emerald-500/15 text-emerald-800 dark:text-emerald-300', l.kind === 'removed' && 'bg-red-500/15 text-red-800 line-through dark:text-red-300')}>
            {l.kind === 'added' ? '+ ' : l.kind === 'removed' ? '− ' : '  '}
            {l.text || ' '}
          </div>
        ))}
    </pre>
  )
}

/** Asks for a reason, then calls back. */
function WithReason({ label, onConfirm, busy }: { label: string; onConfirm: (reason: string) => void; busy: boolean }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  if (!open)
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        {label}
      </Button>
    )
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Motivo (queda en la auditoría)" className="h-8 w-72 text-xs" />
      <Button size="sm" disabled={reason.trim().length < 10 || busy} onClick={() => onConfirm(reason.trim())}>
        Confirmar
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Cancelar
      </Button>
    </span>
  )
}

function Editor({ prompt, onDone }: { prompt: PromptView; onDone: () => void }) {
  const save = useSavePromptDraft()
  const [text, setText] = useState(prompt.draft?.text ?? prompt.text)
  const [reason, setReason] = useState(prompt.draft?.reason ?? '')
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <span className="font-medium">Borrador</span>
      <Textarea rows={14} value={text} onChange={(e) => setText(e.target.value)} className="font-mono text-xs" />
      {prompt.placeholders.length > 0 && (
        <span className="text-xs text-muted-foreground">
          Deben quedar: {prompt.placeholders.map((p) => `{${p}}`).join(', ')}. Para escribir una llave literal usa {'{{'} o {'}}'}.
        </span>
      )}
      <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Por qué lo cambias (mínimo 10 caracteres)" />
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={save.isPending || reason.trim().length < 10}
          onClick={() =>
            save.mutate(
              { name: prompt.name, text, reason: reason.trim() },
              {
                onSuccess: () => {
                  toast.success('Borrador guardado. Pruébalo en una evaluación antes de publicarlo.')
                  onDone()
                },
                onError: (e) => toast.error(errorDetail(e)),
              },
            )
          }
        >
          {save.isPending && <Loader2 className="size-3.5 animate-spin" />} Guardar borrador
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancelar
        </Button>
      </div>
    </div>
  )
}

function DraftPanel({ prompt }: { prompt: PromptView }) {
  const draft = prompt.draft!
  const publish = usePublishPromptDraft()
  const discard = useDiscardPromptDraft()
  const [acknowledged, setAcknowledged] = useState(false)
  const tried = draft.evaluations.filter((e) => e.status === 'completed')
  const canPublish = prompt.evaluated ? tried.length > 0 : acknowledged
  return (
    <div className="flex flex-col gap-2 rounded-md border border-amber-500/50 p-3">
      <span className="font-medium">
        Borrador de {draft.created_by} · {date(draft.created_at)}
      </span>
      <span className="text-muted-foreground">Motivo: {draft.reason}</span>
      <Diff before={prompt.text} after={draft.text} />
      {prompt.evaluated ? (
        <div className="flex flex-col gap-1">
          <span className="font-medium">Evaluaciones con este borrador</span>
          {draft.evaluations.length === 0 && (
            <span className="text-muted-foreground">
              Ninguna todavía. En{' '}
              <Link to="/evaluation" className="underline">
                Evaluación
              </Link>
              , abre una suite y córrela marcando este borrador; compara el resultado con la corrida anterior.
            </span>
          )}
          {draft.evaluations.map((e) => (
            <span key={e.run_id}>
              <Link to={`/evaluation/${e.suite_id}`} className="underline">
                {e.suite_name}
              </Link>{' '}
              · {date(e.created_at)} · {e.status === 'completed' ? `campos ${percent(e.fields)}` : e.status}
            </span>
          ))}
        </div>
      ) : (
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
          Ninguna evaluación ejercita esta instrucción: publico sin prueba automática y revisaré sus resultados.
        </label>
      )}
      {isAISpecialist() && (
        <div className="flex gap-2">
          <Button
            size="sm"
            disabled={!canPublish || publish.isPending}
            title={prompt.evaluated && !tried.length ? 'Primero corre una evaluación con este borrador' : undefined}
            onClick={() =>
              publish.mutate(
                { name: prompt.name, acknowledge: acknowledged },
                { onSuccess: () => toast.success('Publicado: en uso para lo que se procese desde ahora.'), onError: (e) => toast.error(errorDetail(e)) },
              )
            }
          >
            Publicar
          </Button>
          <Button size="sm" variant="ghost" disabled={discard.isPending} onClick={() => discard.mutate(prompt.name, { onSuccess: () => toast.success('Borrador descartado.') })}>
            Descartar
          </Button>
        </div>
      )}
    </div>
  )
}

function PromptCard({ prompt, used, from }: { prompt: PromptView; used: string | undefined; from: string }) {
  const restore = useRestorePrompt()
  const [editing, setEditing] = useState(false)
  const specialist = isAISpecialist()
  const back = (version: string, reason: string) =>
    restore.mutate({ name: prompt.name, version, reason }, { onSuccess: () => toast.success('Listo: esa versión está en uso.'), onError: (e) => toast.error(errorDetail(e)) })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {prompt.label}
          {prompt.source === 'edited' && <Badge variant="outline">editada</Badge>}
          <Used prompt={prompt} used={used} from={from} />
          {prompt.draft && <Badge variant="outline" className="border-amber-600 text-amber-700 dark:text-amber-400">con borrador</Badge>}
        </CardTitle>
        <CardDescription>{prompt.purpose}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <span className="text-muted-foreground">
          Versión <code>{prompt.version}</code> · en uso desde {date(prompt.since)} · usada en {prompt.runs} {prompt.runs === 1 ? 'corrida' : 'corridas'}
          {prompt.source === 'edited' && ` · publicada por ${prompt.published_by} el ${date(prompt.published_at)}: «${prompt.published_reason}»`}
        </span>
        <details>
          <summary className="cursor-pointer text-muted-foreground">Ver el texto</summary>
          <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">{prompt.text}</pre>
          {prompt.placeholders.length > 0 && (
            <div className="mt-2 flex flex-col gap-0.5 text-xs text-muted-foreground">
              <span>Las partes entre llaves las completa la plataforma en cada uso:</span>
              {prompt.placeholders.map((name) => (
                <span key={name}>
                  <code>{`{${name}}`}</code>: {FILLED[name] ?? 'un dato del caso'}
                </span>
              ))}
            </div>
          )}
        </details>

        {prompt.draft && !editing && <DraftPanel prompt={prompt} />}
        {editing && <Editor prompt={prompt} onDone={() => setEditing(false)} />}
        {specialist && !editing && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              {prompt.draft ? 'Editar el borrador' : 'Proponer un cambio'}
            </Button>
            {prompt.source === 'edited' && <WithReason label="Volver al texto original" busy={restore.isPending} onConfirm={(r) => back(prompt.code_version, r)} />}
          </div>
        )}

        {prompt.earlier.length > 0 && (
          <details>
            <summary className="cursor-pointer text-muted-foreground">Versiones anteriores ({prompt.earlier.length})</summary>
            {prompt.earlier.map((e) => (
              <div key={e.version} className="mt-3 flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">
                  <code>{e.version}</code> · desde {date(e.first_seen_at)} · usada en {e.runs} corridas
                  {e.published_by && ` · publicada por ${e.published_by}: «${e.reason}»`}
                  {e.version === prompt.code_version && ' · texto original'}
                </span>
                <Diff before={e.text} after={prompt.text} />
                {specialist && <WithReason label="Volver a esta versión" busy={restore.isPending} onConfirm={(r) => back(e.version, r)} />}
              </div>
            ))}
          </details>
        )}
      </CardContent>
    </Card>
  )
}

export function PromptsPage() {
  const [params] = useSearchParams()
  const caseId = params.get('case') ?? undefined
  const evalRunId = params.get('eval_run') ?? undefined
  const { data: prompts, isLoading } = usePrompts()
  const { data: caseResult } = useCaseResult(caseId)
  const { data: evalRun } = useEvalRun(evalRunId, undefined)
  const used = caseResult?.run?.provenance?.prompts ?? evalRun?.provenance?.prompts
  const from = caseId ? 'Este expediente' : 'Esta corrida'

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Instrucciones al modelo</h1>
        <p className="text-muted-foreground">
          Lo que la plataforma le pide al modelo en cada tarea. Cada instrucción tiene una versión: si su texto cambia, la versión cambia, y cada
          expediente y cada evaluación guardan con cuál se hicieron.{' '}
          {isAISpecialist()
            ? 'Como especialista IA puedes proponer cambios: se guardan como borrador, se prueban en una evaluación y luego se publican.'
            : 'Solo el rol Especialista IA puede cambiarlas.'}
        </p>
        {(caseId || evalRunId) && (
          <p className="mt-2 text-sm">
            Mostrando con qué versión se hizo{' '}
            {caseId ? (
              <Link to={`/cases/${caseId}`} className="underline">
                {caseResult?.case.external_ref ?? 'el expediente'}
              </Link>
            ) : (
              'la corrida de evaluación'
            )}
            {caseResult?.run && ` (corrida ${caseResult.run.run_number})`}.{' '}
            <Link to="/prompts" className="underline">
              Ver todas sin filtro
            </Link>
          </p>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        (prompts ?? []).map((p) => <PromptCard key={p.name} prompt={p} used={used?.[p.name]} from={from} />)
      )}
    </div>
  )
}
