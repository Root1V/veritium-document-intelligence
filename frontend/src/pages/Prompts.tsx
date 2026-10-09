// The instructions the platform gives the models (VRT-46), read only:
// what each one is for, the version in use and since when, its text, and
// its earlier versions. Opened from a case or an evaluation run, it says
// which version that run used. Editing them, governed, is VRT-63.
import { Link, useSearchParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useCaseResult, useEvalRun, usePrompts } from '@/lib/queries'
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
          expediente y cada evaluación guardan con cuál se hicieron. Aquí solo se consultan.
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
        (prompts ?? []).map((p) => (
          <Card key={p.name}>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2">
                {p.label}
                <Used prompt={p} used={used?.[p.name]} from={from} />
              </CardTitle>
              <CardDescription>{p.purpose}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              <span className="text-muted-foreground">
                Versión <code>{p.version}</code> · en uso desde {date(p.since)} · usada en {p.runs} {p.runs === 1 ? 'corrida' : 'corridas'}
              </span>
              <details>
                <summary className="cursor-pointer text-muted-foreground">Ver el texto</summary>
                <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">{p.text}</pre>
                {p.placeholders.length > 0 && (
                  <div className="mt-2 flex flex-col gap-0.5 text-xs text-muted-foreground">
                    <span>Las partes entre llaves las completa la plataforma en cada uso:</span>
                    {p.placeholders.map((name) => (
                      <span key={name}>
                        <code>{`{${name}}`}</code>: {FILLED[name] ?? 'un dato del caso'}
                      </span>
                    ))}
                  </div>
                )}
              </details>
              {p.earlier.length > 0 && (
                <details>
                  <summary className="cursor-pointer text-muted-foreground">Versiones anteriores ({p.earlier.length})</summary>
                  {p.earlier.map((e) => (
                    <div key={e.version} className="mt-2 flex flex-col gap-1">
                      <span className="text-xs text-muted-foreground">
                        <code>{e.version}</code> · desde {date(e.first_seen_at)} · usada en {e.runs} corridas
                      </span>
                      <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">{e.text}</pre>
                    </div>
                  ))}
                </details>
              )}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  )
}
