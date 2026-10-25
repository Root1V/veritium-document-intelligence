// The instructions the platform gives the models (VRT-46, VRT-63, VRT-93):
// a list by stage, each with its state in a word, and the chosen one in full —
// its text with the parts the platform fills in marked, its draft (what
// changes, what tried it, publish) and its history (undo in one click).
// Opened from a case or an evaluation run, it says which version that run
// used. An AI specialist changes them; everyone else reads.
import { Fragment, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Loader2, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { SharedConfigNote } from '@/components/layout/SharedConfigNote'
import { PromptEditorDialog } from '@/components/prompts/PromptEditorDialog'
import { ToneBadge } from '@/components/StatusBadge'
import { errorDetail } from '@/lib/apiErrors'
import { canEditPrompts } from '@/lib/auth'
import { percent, runLabel } from '@/lib/evaluation'
import type { Tone } from '@/lib/labels'
import { FILLED, STAGES, shortVersion } from '@/lib/prompts'
import { cn } from '@/lib/utils'
import { diffLines } from '@/lib/textDiff'
import { useCaseResult, useDiscardPromptDraft, useEvalRun, usePrompts, usePublishPromptDraft, useRestorePrompt } from '@/lib/queries'
import type { PromptView } from '@/types/api'

const date = (iso: string | null) => (iso ? new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' }) : '—')

/** An instruction's state, in a word and a color. */
function stateOf(p: PromptView): { tone: Tone; label: string } {
  if (p.draft) return { tone: 'warn', label: 'Con borrador' }
  if (p.source === 'edited') return { tone: 'busy', label: 'Editada' }
  return { tone: 'neutral', label: 'Original' }
}

/** The text, with each part the platform fills in marked and explained on hover. */
function PromptText({ text }: { text: string }) {
  return (
    <pre className="max-h-[60svh] overflow-auto rounded-lg border bg-card p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
      {text.split(/(\{\{|\}\}|\{[a-z_]+\})/).map((part, i) =>
        /^\{[a-z_]+\}$/.test(part) ? (
          <span key={i} className="rounded bg-primary/10 px-1 font-semibold text-primary" title={`Aquí va ${FILLED[part.slice(1, -1)] ?? 'un dato del caso'}`}>
            {part}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </pre>
  )
}

function Diff({ before, after }: { before: string; after: string }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-lg border bg-card p-3 text-xs whitespace-pre-wrap">
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

function DraftTab({ prompt }: { prompt: PromptView }) {
  const draft = prompt.draft!
  const publish = usePublishPromptDraft()
  const discard = useDiscardPromptDraft()
  const [acknowledged, setAcknowledged] = useState(false)
  const tried = draft.evaluations.filter((e) => e.status === 'completed')
  const canPublish = prompt.evaluated ? tried.length > 0 : acknowledged

  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="flex flex-col gap-1 rounded-lg bg-muted/50 px-3 py-2.5">
        <span>
          <span className="text-muted-foreground">Propuesto por </span>
          {draft.created_by} <span className="text-muted-foreground">el {date(draft.created_at)}</span>
        </span>
        <span>
          <span className="text-muted-foreground">Motivo: </span>
          {draft.reason}
        </span>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-muted-foreground">Qué cambia respecto de la versión en uso</span>
        <Diff before={prompt.text} after={draft.text} />
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">Antes de publicar</span>
        {prompt.evaluated ? (
          draft.evaluations.length === 0 ? (
            <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5">
              Pruébalo primero. En{' '}
              <Link to="/evaluation" className="font-medium underline">
                Evaluación
              </Link>
              , corre un conjunto de prueba marcando este borrador y compara con la corrida anterior.
            </p>
          ) : (
            <ul className="divide-y rounded-lg border bg-card">
              {draft.evaluations.map((e) => (
                <li key={e.run_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                  <Link to={`/evaluation/${e.suite_id}`} className="font-medium underline-offset-4 hover:underline">
                    {e.suite_name}
                  </Link>
                  <span className="text-xs text-muted-foreground">
                    {runLabel(e)}
                    {e.status === 'completed' && ` · datos acertados ${percent(e.fields)}`}
                  </span>
                </li>
              ))}
            </ul>
          )
        ) : (
          <label className="flex items-start gap-2 rounded-lg border px-3 py-2.5">
            <input type="checkbox" className="mt-1" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
            Ninguna evaluación ejercita esta instrucción: publico sin prueba automática y revisaré sus resultados.
          </label>
        )}
      </div>

      {canEditPrompts() && (
        <div className="flex flex-wrap gap-2">
          <Button
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
          <Button variant="ghost" disabled={discard.isPending} onClick={() => discard.mutate(prompt.name, { onSuccess: () => toast.success('Borrador descartado.') })}>
            Descartar borrador
          </Button>
        </div>
      )}
    </div>
  )
}

function Detail({ prompt, used, from }: { prompt: PromptView; used: string | undefined; from: string }) {
  const restore = useRestorePrompt()
  const [editing, setEditing] = useState(false)
  const specialist = canEditPrompts()
  const state = stateOf(prompt)
  const earlierUsed = used && used !== prompt.version ? prompt.earlier.find((e) => e.version === used) : undefined
  const back = (version: string, reason: string) =>
    restore.mutate({ name: prompt.name, version, reason }, { onSuccess: () => toast.success('Listo: esa versión está en uso.'), onError: (e) => toast.error(errorDetail(e)) })

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">{prompt.label}</h2>
            <ToneBadge tone={state.tone} label={state.label} />
          </div>
          <p className="text-sm text-muted-foreground">{prompt.purpose}</p>
        </div>
        {specialist && (
          <Button variant="outline" className="shrink-0" onClick={() => setEditing(true)}>
            <Pencil className="size-4" /> {prompt.draft ? 'Editar el borrador' : 'Proponer un cambio'}
          </Button>
        )}
      </div>

      {used && (
        <div className={cn('rounded-lg border px-3 py-2.5 text-sm', used === prompt.version ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-amber-500/30 bg-amber-500/5')}>
          {used === prompt.version
            ? `${from} usó esta misma versión.`
            : `${from} usó una versión anterior${earlierUsed ? `, la del ${date(earlierUsed.first_seen_at)}` : ''}: mírala en Historial.`}
        </div>
      )}

      <div className="grid grid-cols-3 gap-3 text-sm">
        {[
          ['Versión en uso', shortVersion(prompt.version)],
          ['En uso desde', date(prompt.since)],
          ['Usada en', `${prompt.runs} ${prompt.runs === 1 ? 'corrida' : 'corridas'}`],
        ].map(([label, value]) => (
          <div key={label} className="flex flex-col gap-0.5 rounded-lg border bg-card px-3 py-2">
            <span className="text-xs text-muted-foreground">{label}</span>
            <span className="font-medium">{value}</span>
          </div>
        ))}
      </div>
      {prompt.source === 'edited' && (
        <p className="-mt-2 text-xs text-muted-foreground">
          Publicada por {prompt.published_by} el {date(prompt.published_at)}: «{prompt.published_reason}»
        </p>
      )}

      <Tabs defaultValue={prompt.draft ? 'draft' : 'text'}>
        <TabsList>
          <TabsTrigger value="text">Texto</TabsTrigger>
          {prompt.draft && <TabsTrigger value="draft">Borrador</TabsTrigger>}
          <TabsTrigger value="history">Historial ({prompt.earlier.length})</TabsTrigger>
        </TabsList>
        <TabsContent value="text" className="mt-3 flex flex-col gap-2">
          <PromptText text={prompt.text} />
          {prompt.placeholders.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Lo marcado en azul lo completa la plataforma en cada uso: {prompt.placeholders.map((p) => FILLED[p] ?? p).join('; ')}.
            </p>
          )}
        </TabsContent>
        {prompt.draft && (
          <TabsContent value="draft" className="mt-3">
            <DraftTab prompt={prompt} />
          </TabsContent>
        )}
        <TabsContent value="history" className="mt-3 flex flex-col gap-4">
          {specialist && prompt.source === 'edited' && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2.5 text-sm">
              <span className="flex-1">Está en uso un texto editado. Puedes volver al texto original de la plataforma.</span>
              <WithReason label="Volver al texto original" busy={restore.isPending} onConfirm={(r) => back(prompt.code_version, r)} />
            </div>
          )}
          {prompt.earlier.length === 0 && <p className="text-sm text-muted-foreground">Es la única versión que ha tenido.</p>}
          {prompt.earlier.map((e) => (
            <div key={e.version} className={cn('flex flex-col gap-2 rounded-lg border p-3', e.version === used && 'border-amber-500/50')}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm">
                  <span className="font-medium">Versión {shortVersion(e.version)}</span>
                  <span className="text-muted-foreground">
                    {' '}
                    · desde {date(e.first_seen_at)} · {e.runs} {e.runs === 1 ? 'corrida' : 'corridas'}
                    {e.version === prompt.code_version && ' · texto original'}
                    {e.version === used && ` · la que usó ${from.toLowerCase()}`}
                  </span>
                </span>
                {specialist && <WithReason label="Volver a esta versión" busy={restore.isPending} onConfirm={(r) => back(e.version, r)} />}
              </div>
              {e.published_by && <span className="text-xs text-muted-foreground">Publicada por {e.published_by}: «{e.reason}»</span>}
              <details>
                <summary className="w-fit cursor-pointer text-xs text-muted-foreground select-none hover:text-foreground">Qué cambió desde entonces</summary>
                <div className="mt-2">
                  <Diff before={e.text} after={prompt.text} />
                </div>
              </details>
            </div>
          ))}
        </TabsContent>
      </Tabs>

      {editing && <PromptEditorDialog prompt={prompt} onClose={() => setEditing(false)} />}
    </div>
  )
}

export function PromptsPage() {
  const [params] = useSearchParams()
  const caseId = params.get('case') ?? undefined
  const evalRunId = params.get('eval_run') ?? undefined
  const { data: prompts, isLoading, isError } = usePrompts()
  const { data: caseResult } = useCaseResult(caseId)
  const { data: evalRun } = useEvalRun(evalRunId, undefined)
  const used = caseResult?.run?.provenance?.prompts ?? evalRun?.provenance?.prompts
  const from = caseId ? 'Este expediente' : 'Esta corrida'
  const [picked, setPicked] = useState<string | undefined>()
  const byName = new Map((prompts ?? []).map((p) => [p.name, p]))
  const stages = [...STAGES, { name: 'Otras', prompts: (prompts ?? []).map((p) => p.name).filter((n) => !STAGES.some((s) => s.prompts.includes(n))) }]
    .map((s) => ({ name: s.name, prompts: s.prompts.map((n) => byName.get(n)).filter((p): p is PromptView => !!p) }))
    .filter((s) => s.prompts.length)
  const ordered = stages.flatMap((s) => s.prompts)
  // What needs attention first: a version the run didn't share, then a draft waiting.
  const shown =
    byName.get(picked ?? '') ??
    ordered.find((p) => used?.[p.name] && used[p.name] !== p.version) ??
    ordered.find((p) => p.draft) ??
    ordered[0]

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Instrucciones al modelo</h1>
        <p className="text-muted-foreground">
          Lo que la plataforma le pide al modelo en cada tarea. Cada cambio queda como una versión nueva, y cada expediente guarda con cuál se hizo.{' '}
          {canEditPrompts() ? 'Un cambio se propone como borrador, se prueba en una evaluación y luego se publica.' : 'Solo el rol Especialista IA puede cambiarlas.'}
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
      <SharedConfigNote show={!canEditPrompts()} />

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError || !shown ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar las instrucciones: el servidor de Veritium no responde.</p>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[18rem_1fr]">
          <aside className="flex flex-col gap-4 xl:sticky xl:top-20">
            {stages.map((s) => (
              <div key={s.name} className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">{s.name}</span>
                <ul className="flex flex-col gap-1">
                  {s.prompts.map((p) => {
                    const state = stateOf(p)
                    const other = used?.[p.name] && used[p.name] !== p.version
                    return (
                      <li key={p.name}>
                        <button
                          type="button"
                          onClick={() => setPicked(p.name)}
                          className={cn(
                            'flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm transition',
                            p.name === shown.name ? 'border-primary bg-primary/5 font-medium' : 'bg-card hover:border-primary/40',
                          )}
                        >
                          <span className="truncate">{p.label}</span>
                          {other ? <ToneBadge tone="warn" label="Otra versión" /> : state.tone !== 'neutral' && <ToneBadge tone={state.tone} label={state.label} />}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            ))}
          </aside>
          <div className="min-w-0 rounded-2xl border bg-muted/20 p-5">
            <Detail key={shown.name} prompt={shown} used={used?.[shown.name]} from={from} />
          </div>
        </div>
      )}
    </div>
  )
}
