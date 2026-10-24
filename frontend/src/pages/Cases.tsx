import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useCases, useProcessProfiles } from '@/lib/queries'
import { VERDICT_LABEL } from '@/lib/verdict'
import { ToneBadge } from '@/components/StatusBadge'
import { canExecute, isAdmin } from '@/lib/auth'
import { DeleteButton } from '@/components/DeleteButton'
import { UploadLinkDialog } from '@/components/cases/UploadLinkDialog'
import { ProgressFunnel } from '@/components/cases/ProgressFunnel'

export const DELETE_CASE =
  'Se eliminará para siempre el expediente con sus documentos, archivos, lecturas y hallazgos. Solo queda el registro de quién lo eliminó y por qué.'

const VERDICT_TONE = { continue: 'ok', human_review: 'warn', return_to_client: 'bad' } as const
const CHANNEL_LABEL: Record<string, string> = { online: 'En línea', backoffice: 'Oficina', bulk: 'Carga masiva' }

export function CasesPage() {
  const { data: cases, isLoading } = useCases()
  const { data: profiles } = useProcessProfiles()
  const processName = (key: string) => profiles?.find((p) => p.key === key)?.name ?? key

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Expedientes</h1>
          <p className="text-muted-foreground">Cada expediente con su veredicto. Ábrelo para ver el resultado completo y su evidencia.</p>
        </div>
        {canExecute() && <UploadLinkDialog />}
      </div>
      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Expediente</TableHead>
              <TableHead>Proceso</TableHead>
              <TableHead>Canal</TableHead>
              <TableHead>Avance</TableHead>
              <TableHead>Decisión</TableHead>
              <TableHead>Llegó</TableHead>
              {isAdmin() && <TableHead className="w-10" />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {(cases ?? []).map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <Link to={`/cases/${c.id}`} className="font-medium underline-offset-4 hover:underline">
                    {c.external_ref ?? c.id.slice(0, 8)}
                  </Link>
                </TableCell>
                <TableCell className="text-sm">{c.profile ? processName(c.profile.key) : '—'}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{CHANNEL_LABEL[c.channel] ?? c.channel}</TableCell>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <span className="text-sm">{c.progress.status_label}</span>
                    {c.status !== 'completed' || c.progress.failed_documents ? <ProgressFunnel progress={c.progress} compact /> : null}
                  </div>
                </TableCell>
                <TableCell>
                  {c.verdict ? (
                    <ToneBadge tone={VERDICT_TONE[c.verdict]} label={VERDICT_LABEL[c.verdict]} />
                  ) : c.status === 'processing' || c.status === 'uploaded' ? (
                    <ToneBadge tone="busy" label="En proceso" />
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">{new Date(c.created_at).toLocaleString('es', { dateStyle: 'medium', timeStyle: 'short' })}</TableCell>
                {isAdmin() && (
                  <TableCell>
                    <DeleteButton iconOnly askReason path={`/v1/cases/${c.id}`} label="Eliminar expediente" question={DELETE_CASE} />
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
