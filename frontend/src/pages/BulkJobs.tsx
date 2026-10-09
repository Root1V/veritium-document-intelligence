// Bulk jobs (VRT-48): many cases at once from the backoffice — a ZIP with
// one folder per case. Its cases advance a few at a time so online work is
// never held back; each job shows how far it is and how its cases ended.
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Download, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ProgressFunnel } from '@/components/cases/ProgressFunnel'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute } from '@/lib/auth'
import { downloadFile, useBulkJob, useBulkJobs, useProcessProfiles, useSubmitBulkJob } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { BulkJobSummary, BulkOutcome } from '@/types/api'

const OUTCOMES: { key: BulkOutcome; label: string; dot: string }[] = [
  { key: 'continue', label: 'Continuar', dot: 'bg-emerald-500' },
  { key: 'human_review', label: 'Revisión humana', dot: 'bg-amber-500' },
  { key: 'return_to_client', label: 'Devolver al cliente', dot: 'bg-red-500' },
  { key: 'failed', label: 'Con error', dot: 'bg-slate-500' },
  { key: 'pending', label: 'En curso', dot: 'bg-sky-500' },
]
const OUTCOME = Object.fromEntries(OUTCOMES.map((o) => [o.key, o]))

function downloadResults(job: { id: string }) {
  downloadFile(`/v1/bulk-jobs/${job.id}/results`, {}, 'resultados.csv').catch((e) => toast.error(errorDetail(e)))
}

function Outcomes({ job }: { job: BulkJobSummary }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
      {OUTCOMES.filter((o) => job.outcomes[o.key]).map((o) => (
        <span key={o.key} className="flex items-center gap-1.5">
          <span className={cn('size-2 rounded-full', o.dot)} />
          {o.label} {job.outcomes[o.key]}
        </span>
      ))}
    </div>
  )
}

function Advance({ job }: { job: BulkJobSummary }) {
  const done = job.cases - (job.outcomes.pending ?? 0)
  return (
    <div className="flex min-w-40 flex-col gap-1">
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-primary transition-all" style={{ width: `${job.cases ? (100 * done) / job.cases : 0}%` }} />
      </div>
      <span className="text-xs text-muted-foreground">
        {job.finished_at ? 'Terminada' : 'En proceso'} · {done} de {job.cases} expedientes
      </span>
    </div>
  )
}

function NewBulkJob() {
  const submit = useSubmitBulkJob()
  const { data: profiles } = useProcessProfiles()
  const [profile, setProfile] = useState('')
  const [name, setName] = useState('')
  const [archive, setArchive] = useState<File | null>(null)
  const published = (profiles ?? []).filter((p) => p.active_version !== null)
  const result = submit.data

  return (
    <Card>
      <CardHeader>
        <CardTitle>Nueva carga</CardTitle>
        <CardDescription>Prepara un archivo ZIP así:</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
          <li>
            Una carpeta por expediente. El nombre de la carpeta es la referencia del expediente (por ejemplo <code>EXP-0001</code>).
          </li>
          <li>Dentro de cada carpeta, los documentos de ese expediente (PDF o fotos).</li>
          <li>Comprime todas las carpetas en un solo ZIP.</li>
        </ol>
        <p className="text-muted-foreground">
          Opcional: agrega en el ZIP un <strong>manifiesto</strong> (Excel o CSV) para indicar, por expediente, otro perfil o los datos del proceso.
          {profile && (
            <Button
              variant="link"
              size="sm"
              className="h-auto px-1"
              onClick={() => downloadFile('/v1/bulk-jobs/template', { profile }, 'manifiesto.csv').catch((e) => toast.error(errorDetail(e)))}
            >
              <Download className="size-3.5" /> Descargar manifiesto de ejemplo
            </Button>
          )}
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Perfil de proceso</span>
            <Select value={profile} onValueChange={setProfile}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Elige el perfil…" />
              </SelectTrigger>
              <SelectContent>
                {published.map((p) => (
                  <SelectItem key={p.key} value={p.key}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Nombre (opcional)</span>
            <Input placeholder="p. ej. Convenios octubre" value={name} onChange={(e) => setName(e.target.value)} className="w-64" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Archivo ZIP</span>
            <Input type="file" accept=".zip,application/zip" onChange={(e) => setArchive(e.target.files?.[0] ?? null)} className="w-72" />
          </label>
          <Button
            disabled={!archive || !profile || submit.isPending}
            onClick={() => archive && submit.mutate({ archive, profile, name: name.trim() }, { onError: (e) => toast.error(errorDetail(e)) })}
          >
            {submit.isPending && <Loader2 className="size-4 animate-spin" />} Enviar carga
          </Button>
        </div>
        {result && (
          <div className="flex flex-col gap-1 rounded-md border p-3">
            <span>
              Se recibieron <strong>{result.cases}</strong> expedientes.{' '}
              <Link to={`/bulk/${result.id}`} className="underline">
                Ver avance
              </Link>
            </span>
            {result.skipped.length > 0 && (
              <div className="text-amber-700 dark:text-amber-400">
                No se procesarán:
                <ul className="list-disc pl-5">
                  {result.skipped.map((s, i) => (
                    <li key={i}>{s.reference ? `${s.reference}: ${s.reason}` : s.reason}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function BulkJobsPage() {
  const { data: jobs, isLoading } = useBulkJobs()
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Cargas masivas</h1>
        <p className="text-muted-foreground">Muchos expedientes de una vez. Avanzan de a pocos para no retrasar las solicitudes en línea.</p>
      </div>
      {canExecute() && <NewBulkJob />}
      <Card>
        <CardHeader>
          <CardTitle>Cargas</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          ) : !jobs?.length ? (
            <span className="text-sm text-muted-foreground">Todavía no hay cargas.</span>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Carga</TableHead>
                  <TableHead>Avance</TableHead>
                  <TableHead>Resultado</TableHead>
                  <TableHead>Enviada</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.map((j) => (
                  <TableRow key={j.id}>
                    <TableCell>
                      <Link to={`/bulk/${j.id}`} className="font-medium underline-offset-4 hover:underline">
                        {j.name}
                      </Link>
                      {j.skipped.length > 0 && <div className="text-xs text-amber-700 dark:text-amber-400">{j.skipped.length} sin procesar</div>}
                    </TableCell>
                    <TableCell>
                      <Advance job={j} />
                    </TableCell>
                    <TableCell>
                      <Outcomes job={j} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      <div>{new Date(j.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}</div>
                      <div>{j.created_by}</div>
                    </TableCell>
                    <TableCell>
                      <Button variant="outline" size="sm" onClick={() => downloadResults(j)}>
                        <Download className="size-3.5" /> Resultados
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function BulkJobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const { data: job, isLoading } = useBulkJob(jobId)
  if (isLoading || !job) return <Loader2 className="size-6 animate-spin text-muted-foreground" />

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{job.name}</h1>
        <Button variant="outline" size="sm" onClick={() => downloadResults(job)}>
          <Download className="size-3.5" /> Descargar resultados
        </Button>
        <Link to="/bulk" className="ml-auto text-sm underline">
          Volver a cargas masivas
        </Link>
      </div>
      <Card>
        <CardContent className="flex flex-wrap items-center gap-6 py-4">
          <Advance job={job} />
          <Outcomes job={job} />
        </CardContent>
      </Card>
      {job.skipped.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>No se procesaron</CardTitle>
            <CardDescription>Corrígelos y envíalos en una nueva carga.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-1 text-sm">
            {job.skipped.map((s, i) => (
              <span key={i}>{s.reference ? `${s.reference}: ${s.reason}` : s.reason}</span>
            ))}
          </CardContent>
        </Card>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Expediente</TableHead>
            <TableHead>Perfil</TableHead>
            <TableHead>Avance</TableHead>
            <TableHead>Resultado</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {job.items.map((c) => (
            <TableRow key={c.id}>
              <TableCell>
                <Link to={`/cases/${c.id}`} className="font-medium underline-offset-4 hover:underline">
                  {c.external_ref ?? c.id.slice(0, 8)}
                </Link>
              </TableCell>
              <TableCell className="text-sm">{c.profile ?? '—'}</TableCell>
              <TableCell>
                <div className="flex flex-col gap-1">
                  <span className="text-sm">{c.progress.status_label}</span>
                  {c.outcome === 'pending' && <ProgressFunnel progress={c.progress} compact />}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant="outline" className="gap-1.5">
                  <span className={cn('size-2 rounded-full', OUTCOME[c.outcome].dot)} />
                  {OUTCOME[c.outcome].label}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
