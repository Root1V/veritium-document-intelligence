// Evaluation suites (VRT-42, VRT-107): documents whose right answer is known,
// run against the current models, prompts and document types. Each suite is
// a card with its last result in a traffic light; a new one is made in a
// dialog that asks the way first — the corrections, or a table.
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ClipboardCheck, FlaskConical, Loader2, Plus, Table2 } from 'lucide-react'
import { DeleteButton } from '@/components/DeleteButton'
import { NewSuiteDialog } from '@/components/evaluation/NewSuiteDialog'
import { Button } from '@/components/ui/button'
import { canExecute, isAISpecialist } from '@/lib/auth'
import { runLabel, toneOf } from '@/lib/evaluation'
import { useEvalSuites } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { EvalRate } from '@/types/api'

function Rate({ label, rate }: { label: string; rate: EvalRate | null | undefined }) {
  const tone = toneOf(rate)
  const value = rate?.accuracy ?? null
  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className={cn('font-semibold', tone.text)}>{value === null ? '—' : `${rate!.correct} de ${rate!.evaluated}`}</span>
      </span>
      <span className="h-1.5 overflow-hidden rounded-full bg-muted">
        <span className={cn('block h-full rounded-full', tone.bar)} style={{ width: `${Math.round((value ?? 0) * 100)}%` }} />
      </span>
    </div>
  )
}

export function EvaluationPage() {
  const { data: suites, isLoading, isError } = useEvalSuites()
  const [creating, setCreating] = useState(false)
  const navigate = useNavigate()
  const may = canExecute() || isAISpecialist()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Evaluación</h1>
          <p className="text-muted-foreground">
            Documentos cuya respuesta correcta ya se conoce. Correrlos mide cuánto acierta la lectura hoy y lo compara con la vez anterior, antes de publicar un cambio.
          </p>
        </div>
        {may && (
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Nuevo conjunto
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar los conjuntos: el servidor de Veritium no responde.</p>
      ) : !suites?.length ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-10 text-center">
          <FlaskConical className="size-8 text-muted-foreground" />
          <p className="max-w-md text-sm text-muted-foreground">
            Todavía no hay conjuntos de prueba. El más rápido es desde las correcciones: usa los documentos que un revisor ya corrigió.
          </p>
          {may && (
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" /> Crear el primero
            </Button>
          )}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {suites.map((s) => {
            const run = s.latest_run
            const Icon = s.source === 'corrections' ? ClipboardCheck : Table2
            return (
              <div key={s.id} className="flex flex-col gap-4 rounded-xl border bg-card p-5">
                <div className="flex items-start gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <Icon className="size-5" />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <Link to={`/evaluation/${s.id}`} className="truncate font-semibold hover:underline">
                      {s.name}
                    </Link>
                    <span className="text-xs text-muted-foreground">
                      {s.case_count} documentos · {s.source === 'corrections' ? 'desde las correcciones' : 'desde una tabla'}
                    </span>
                  </div>
                  {may && (
                    <DeleteButton
                      iconOnly
                      path={`/v1/eval-suites/${s.id}`}
                      label="Eliminar conjunto"
                      question={`Se eliminará para siempre el conjunto «${s.name}» con sus corridas y sus archivos.`}
                    />
                  )}
                </div>
                {run?.metrics ? (
                  <div className="flex flex-col gap-2">
                    <Rate label="Datos leídos bien" rate={run.metrics.fields} />
                    <Rate label="Tipo de documento reconocido" rate={run.metrics.classification} />
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">{run ? `Última corrida: ${runLabel(run)}` : 'Todavía no se corrió.'}</p>
                )}
                <div className="mt-auto flex items-center justify-between gap-2 border-t pt-3">
                  <span className="text-xs text-muted-foreground">{run ? `Última: ${runLabel(run)}` : ''}</span>
                  <Button size="sm" variant="outline" onClick={() => navigate(`/evaluation/${s.id}`)}>
                    Abrir
                  </Button>
                </div>
              </div>
            )
          })}
          {may && (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center text-sm text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
            >
              <Plus className="size-5" />
              <span className="font-medium">Nuevo conjunto</span>
              <span className="text-xs">Desde las correcciones o desde una tabla.</span>
            </button>
          )}
        </div>
      )}

      {creating && <NewSuiteDialog onClose={() => setCreating(false)} onCreated={(s) => navigate(`/evaluation/${s.id}`)} />}
    </div>
  )
}
