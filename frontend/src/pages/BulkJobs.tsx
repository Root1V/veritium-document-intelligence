// Bulk jobs (VRT-48, VRT-109): many cases at once from the backoffice — a ZIP
// with one folder per case. Its cases advance a few at a time so online work
// is never held back. Each job is a card with how far it is and how its
// cases ended, in one bar of traffic-light colours; a new one is sent from a
// dialog. Deleting a job is done from inside it.
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Download, Loader2, Package, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { NewBulkJobDialog } from '@/components/bulk/NewBulkJobDialog'
import { ProgressFunnel } from '@/components/cases/ProgressFunnel'
import { DeleteButton } from '@/components/DeleteButton'
import { Button } from '@/components/ui/button'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute, isAdmin } from '@/lib/auth'
import { downloadFile, useBulkJob, useBulkJobs, useProcessProfiles } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { BulkJobSummary, BulkOutcome } from '@/types/api'

const OUTCOMES: { key: BulkOutcome; label: string; dot: string; text: string }[] = [
  { key: 'continue', label: 'Continuar', dot: 'bg-emerald-500', text: 'text-emerald-700 dark:text-emerald-400' },
  { key: 'human_review', label: 'Revisión humana', dot: 'bg-amber-500', text: 'text-amber-700 dark:text-amber-400' },
  { key: 'return_to_client', label: 'Devolver al cliente', dot: 'bg-red-500', text: 'text-red-700 dark:text-red-400' },
  { key: 'failed', label: 'Con error', dot: 'bg-slate-500', text: 'text-muted-foreground' },
  { key: 'pending', label: 'En curso', dot: 'bg-sky-500', text: 'text-sky-700 dark:text-sky-400' },
]
const OUTCOME = Object.fromEntries(OUTCOMES.map((o) => [o.key, o]))
const DELETE_JOB = 'Se eliminarán para siempre la carga y todos sus expedientes, con sus documentos y archivos.'
const when = (iso: string) => new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })

function downloadResults(job: { id: string }) {
  downloadFile(`/v1/bulk-jobs/${job.id}/results`, {}, 'resultados.csv').catch((e) => toast.error(errorDetail(e)))
}

/** How the job's cases ended, as one bar, with the count of each colour. */
function Outcomes({ job }: { job: BulkJobSummary }) {
  const present = OUTCOMES.filter((o) => job.outcomes[o.key])
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-2 overflow-hidden rounded-full bg-muted">
        {present.map((o) => (
          <span key={o.key} className={o.dot} style={{ width: `${(100 * (job.outcomes[o.key] ?? 0)) / Math.max(job.cases, 1)}%` }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
        {present.map((o) => (
          <span key={o.key} className="inline-flex items-center gap-1.5">
            <span className={cn('size-2 rounded-full', o.dot)} />
            {o.label} <span className="font-semibold tabular-nums">{job.outcomes[o.key]}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function status(job: BulkJobSummary) {
  const done = job.cases - (job.outcomes.pending ?? 0)
  return job.finished_at ? `Terminada · ${job.cases} expedientes` : `En proceso · ${done} de ${job.cases} expedientes`
}

export function BulkJobsPage() {
  const { data: jobs, isLoading, isError } = useBulkJobs()
  const [creating, setCreating] = useState(false)
  const may = canExecute()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Cargas masivas</h1>
          <p className="text-muted-foreground">Muchos expedientes de una vez. Avanzan de a pocos para no retrasar las solicitudes en línea.</p>
        </div>
        {may && (
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Nueva carga
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar las cargas: el servidor de Veritium no responde.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(jobs ?? []).map((j) => (
            <div key={j.id} className="flex flex-col gap-4 rounded-xl border bg-card p-5">
              <div className="flex items-start gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Package className="size-5" />
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <Link to={`/bulk/${j.id}`} className="truncate font-semibold hover:underline">
                    {j.name}
                  </Link>
                  <span className="text-xs text-muted-foreground">{status(j)}</span>
                </div>
              </div>
              <Outcomes job={j} />
              {j.skipped.length > 0 && <span className="text-xs text-amber-700 dark:text-amber-400">{j.skipped.length} no se procesaron: mira por qué en el detalle.</span>}
              <div className="mt-auto flex items-center justify-between gap-2 border-t pt-3">
                <span className="text-xs text-muted-foreground">
                  {when(j.created_at)} · {j.created_by}
                </span>
                <span className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => downloadResults(j)} title="Descargar los resultados en CSV">
                    <Download className="size-3.5" />
                  </Button>
                  <Button size="sm" variant="outline" asChild>
                    <Link to={`/bulk/${j.id}`}>Abrir</Link>
                  </Button>
                </span>
              </div>
            </div>
          ))}
          {may && (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center text-sm text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
            >
              <Plus className="size-5" />
              <span className="font-medium">Nueva carga</span>
              <span className="text-xs">Un ZIP con una carpeta por expediente.</span>
            </button>
          )}
          {!may && !jobs?.length && <p className="text-sm text-muted-foreground">Todavía no hay cargas.</p>}
        </div>
      )}

      {creating && <NewBulkJobDialog onClose={() => setCreating(false)} />}
    </div>
  )
}

export function BulkJobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const { data: job, isLoading } = useBulkJob(jobId)
  const { data: profiles } = useProcessProfiles()
  const navigate = useNavigate()
  if (isLoading || !job) return <Loader2 className="size-6 animate-spin text-muted-foreground" />

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <Link to="/bulk" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ChevronLeft className="size-4" /> Cargas masivas
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">{job.name}</h1>
          <span className="text-sm text-muted-foreground">
            {status(job)} · enviada el {when(job.created_at)} por {job.created_by}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => downloadResults(job)}>
            <Download className="size-4" /> Descargar resultados
          </Button>
          {isAdmin() && <DeleteButton path={`/v1/bulk-jobs/${job.id}`} label="Eliminar carga" question={DELETE_JOB} onDone={() => navigate('/bulk')} />}
        </div>
      </div>

      <div className="rounded-xl border bg-card p-4">
        <Outcomes job={job} />
      </div>

      {job.skipped.length > 0 && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
          <span className="font-medium text-amber-800 dark:text-amber-300">No se procesaron {job.skipped.length}: corrígelos y envíalos en una nueva carga.</span>
          <ul className="mt-1 list-disc pl-5 text-amber-800 dark:text-amber-300">
            {job.skipped.map((s, i) => (
              <li key={i}>{s.reference ? `${s.reference}: ${s.reason}` : s.reason}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
        {job.items.map((c) => {
          const o = OUTCOME[c.outcome]
          return (
            <Link key={c.id} to={`/cases/${c.id}`} className="group flex items-center gap-3 border-b px-4 py-3 transition last:border-0 hover:bg-muted/50">
              <span className={cn('size-2.5 shrink-0 rounded-full', o.dot)} />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-semibold group-hover:underline">{c.external_ref ?? `Expediente ${c.id.slice(0, 8)}`}</span>
                  <span className="text-xs text-muted-foreground">{(c.profile && profiles?.find((p) => p.key === c.profile)?.name) ?? c.profile ?? 'Sin proceso'}</span>
                </span>
                {c.outcome === 'pending' && (
                  <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {c.progress.status_label}
                    <ProgressFunnel progress={c.progress} compact />
                  </span>
                )}
              </span>
              <span className={cn('w-40 shrink-0 text-sm font-medium', o.text)}>{o.label}</span>
              <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
            </Link>
          )
        })}
      </div>
    </div>
  )
}
