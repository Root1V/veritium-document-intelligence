import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useCases } from '@/lib/queries'
import { VERDICT_LABEL, VERDICT_VARIANT } from '@/lib/verdict'

export function CasesPage() {
  const { data: cases, isLoading } = useCases()

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Expedientes</h1>
        <p className="text-muted-foreground">Cada expediente con su veredicto. Ábrelo para ver el resultado completo y su evidencia.</p>
      </div>
      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Expediente</TableHead>
              <TableHead>Perfil</TableHead>
              <TableHead>Canal</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Veredicto</TableHead>
              <TableHead>Creado</TableHead>
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
                <TableCell className="text-sm">{c.profile ? `${c.profile.key} v${c.profile.version}` : '—'}</TableCell>
                <TableCell className="text-sm">{c.channel}</TableCell>
                <TableCell>
                  <Badge variant="outline">{c.status}</Badge>
                </TableCell>
                <TableCell>{c.verdict ? <Badge variant={VERDICT_VARIANT[c.verdict]}>{VERDICT_LABEL[c.verdict]}</Badge> : '—'}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{new Date(c.created_at).toLocaleString()}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
