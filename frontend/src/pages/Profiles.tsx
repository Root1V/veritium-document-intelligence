import { Link } from 'react-router-dom'
import { Loader2, Pencil, Plus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { isAdmin } from '@/lib/auth'
import { DeleteButton } from '@/components/DeleteButton'
import { useProcessProfiles } from '@/lib/queries'

export function ProfilesPage() {
  const { data: profiles, isLoading } = useProcessProfiles()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Procesos</h1>
          <p className="text-muted-foreground">
            Cada proceso de negocio que usa Veritium: qué documentos o evidencias exige, qué reglas aplica y con qué severidad,
            sobre qué versión del catálogo semántico. Una versión publicada no cambia; un cambio es una versión nueva.
          </p>
        </div>
        {isAdmin() && (
          <Button asChild>
            <Link to="/profiles/new">
              <Plus className="size-4" /> Nuevo proceso
            </Link>
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Proceso</TableHead>
              <TableHead>Versión activa</TableHead>
              <TableHead>Catálogo de datos</TableHead>
              <TableHead>Versiones</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {(profiles ?? []).map((p) => {
              const active = p.versions.find((v) => v.version === p.active_version)
              const draft = p.versions.find((v) => v.status === 'draft')
              const archived = p.versions.length > 0 && p.versions.every((v) => v.status === 'retired')
              return (
                <TableRow key={p.key}>
                  <TableCell>
                    <div className="font-medium">{p.name}</div>
                    <code className="text-xs text-muted-foreground">{p.key}</code>
                    {archived && <Badge variant="secondary" className="ml-2">archivado</Badge>}
                  </TableCell>
                  <TableCell>{p.active_version ? `v${p.active_version}` : '—'}</TableCell>
                  <TableCell>{active ? `v${active.semantic_catalog_version}` : '—'}</TableCell>
                  <TableCell className="text-sm">
                    {p.versions.length} {draft && <Badge variant="outline">borrador v{draft.version}</Badge>}
                    {draft && isAdmin() && (
                      <Link to={`/simulations?profile=${p.key}&version=${draft.version}`} className="ml-2 text-xs underline">
                        probar el borrador
                      </Link>
                    )}
                    {draft && isAdmin() && (
                      <DeleteButton
                        iconOnly
                        label="Descartar borrador"
                        path={`/v1/profiles/${p.key}/versions/${draft.version}`}
                        question={`Se eliminará para siempre el borrador v${draft.version} de «${p.name}».`}
                      />
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {isAdmin() && (
                      <Button asChild variant="outline" size="sm">
                        <Link to={`/profiles/${p.key}/edit`}>
                          <Pencil className="size-3.5" /> Nueva versión
                        </Link>
                      </Button>
                    )}
                    {isAdmin() && p.key !== 'ad-hoc' && !archived && (
                      <DeleteButton
                        iconOnly
                        label="Eliminar proceso"
                        path={`/v1/profiles/${p.key}`}
                        question={`¿Eliminar el proceso «${p.name}»? Si ningún expediente lo usó, se borra del todo; si ya se usó, se archiva: no recibe expedientes nuevos y los existentes conservan su versión.`}
                      />
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
