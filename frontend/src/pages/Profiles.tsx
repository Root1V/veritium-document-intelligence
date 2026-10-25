// The processes (VRT-24, VRT-87): each one as a card that says, in business
// words, whether it is live, what it asks for and checks, how much it is used
// and whether there are unpublished changes — with the next action at hand.
import { Link } from 'react-router-dom'
import { FileText, FlaskConical, Loader2, MoreHorizontal, Pencil, Plus, ShieldCheck, Trash2, Workflow } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useDeleteAction } from '@/components/DeleteButton'
import { isAdmin } from '@/lib/auth'
import { useCases, useProcessProfiles, useProfileVersion } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ProcessProfileSummary } from '@/types/api'

const AD_HOC = 'ad-hoc'
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('es-PE', { day: 'numeric', month: 'short', year: 'numeric' }) : null)
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

function Status({ tone, children }: { tone: 'live' | 'draft' | 'off'; children: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium',
        tone === 'live' && 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
        tone === 'draft' && 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
        tone === 'off' && 'bg-muted text-muted-foreground',
      )}
    >
      <span className={cn('size-1.5 rounded-full', tone === 'live' ? 'bg-emerald-500' : tone === 'draft' ? 'bg-amber-500' : 'bg-muted-foreground')} />
      {children}
    </span>
  )
}

function ProcessCard({ profile, cases }: { profile: ProcessProfileSummary; cases: number }) {
  const active = profile.versions.find((v) => v.version === profile.active_version)
  const draft = profile.versions.find((v) => v.status === 'draft')
  const archived = profile.versions.length > 0 && profile.versions.every((v) => v.status === 'retired')
  const adHoc = profile.key === AD_HOC
  // What it asks for: the published version, or the draft while it has none.
  const { data: shown } = useProfileVersion(profile.key, profile.active_version ?? draft?.version)
  const definition = shown?.definition
  const admin = isAdmin()
  const discard = useDeleteAction({
    path: `/v1/profiles/${profile.key}/versions/${draft?.version}`,
    question: `Se descartarán para siempre los cambios sin publicar de «${profile.name}». La versión publicada sigue igual.`,
  })
  const remove = useDeleteAction({
    path: `/v1/profiles/${profile.key}`,
    question: `¿Eliminar el proceso «${profile.name}»? Si ningún expediente lo usó, se borra del todo; si ya se usó, se archiva: no recibe expedientes nuevos y los existentes conservan su versión.`,
  })
  const name = adHoc ? 'Revisión general' : profile.name
  const description = adHoc ? 'Para documentos que llegan sin un proceso definido: aplica todas las reglas activas.' : profile.description

  return (
    <Card className={cn('flex flex-col', archived && 'opacity-70')}>
      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Workflow className="size-5" />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <Link to={admin ? `/profiles/${profile.key}/edit` : '#'} className="truncate font-semibold hover:underline">
                {name}
              </Link>
              {archived ? <Status tone="off">Archivado</Status> : active ? <Status tone="live">Publicado</Status> : <Status tone="draft">Sin publicar</Status>}
            </div>
            <p className="line-clamp-2 text-sm text-muted-foreground">{description || 'Sin descripción.'}</p>
          </div>
          {admin && !archived && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="size-8 shrink-0" aria-label="Más acciones">
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuItem asChild>
                  <Link to={`/profiles/${profile.key}/edit`}>
                    <Pencil className="size-4" /> Editar
                  </Link>
                </DropdownMenuItem>
                {draft && (
                  <DropdownMenuItem asChild>
                    <Link to={`/simulations?profile=${profile.key}&version=${draft.version}`}>
                      <FlaskConical className="size-4" /> Probar los cambios
                    </Link>
                  </DropdownMenuItem>
                )}
                {(draft || !adHoc) && <DropdownMenuSeparator />}
                {draft && active && (
                  <DropdownMenuItem variant="destructive" disabled={discard.pending} onSelect={discard.run}>
                    <Trash2 className="size-4" /> Descartar cambios sin publicar
                  </DropdownMenuItem>
                )}
                {!adHoc && (
                  <DropdownMenuItem variant="destructive" disabled={remove.pending} onSelect={remove.run}>
                    <Trash2 className="size-4" /> Eliminar proceso
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        <dl className="grid grid-cols-3 gap-2 rounded-lg bg-muted/50 p-3 text-center">
          <div>
            <dt className="text-xs text-muted-foreground">Documentos</dt>
            <dd className="text-lg font-semibold tabular-nums">{definition ? definition.checklist.length : '–'}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Comprobaciones</dt>
            <dd className="text-lg font-semibold tabular-nums">{definition ? (definition.include_all_rules ? 'Todas' : definition.rule_bindings.length) : '–'}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Expedientes</dt>
            <dd className="text-lg font-semibold tabular-nums">{cases}</dd>
          </div>
        </dl>

        {definition && definition.checklist.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {definition.checklist.slice(0, 4).map((c) => (
              <span key={c.key} className="inline-flex max-w-full items-center gap-1 truncate rounded-md border px-2 py-0.5 text-xs text-muted-foreground">
                <FileText className="size-3 shrink-0" /> <span className="truncate">{c.label}</span>
              </span>
            ))}
            {definition.checklist.length > 4 && <span className="px-1 py-0.5 text-xs text-muted-foreground">y {definition.checklist.length - 4} más</span>}
          </div>
        )}

        {draft && active && admin && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm">
            <span className="flex-1 text-amber-800 dark:text-amber-300">Hay cambios sin publicar.</span>
            <Button asChild size="sm" variant="ghost" className="h-7">
              <Link to={`/simulations?profile=${profile.key}&version=${draft.version}`}>Probar</Link>
            </Button>
            <Button asChild size="sm" variant="outline" className="h-7">
              <Link to={`/profiles/${profile.key}/edit`}>Continuar</Link>
            </Button>
          </div>
        )}

        <div className="mt-auto flex items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <ShieldCheck className="size-3.5" />
            {definition?.retention_days ? `Datos personales: ${plural(definition.retention_days, 'día', 'días')}` : 'Datos personales sin plazo'}
          </span>
          <span>{active ? `Versión ${active.version} · ${day(active.published_at) ?? ''}` : draft ? 'Borrador' : '—'}</span>
        </div>
      </CardContent>
    </Card>
  )
}

export function ProfilesPage() {
  const { data: profiles, isLoading } = useProcessProfiles()
  const { data: cases } = useCases()
  const count = (key: string) => (cases ?? []).filter((c) => c.profile?.key === key).length
  // Real processes first, the general review last, archived at the end.
  const archived = (p: ProcessProfileSummary) => p.versions.length > 0 && p.versions.every((v) => v.status === 'retired')
  const ordered = [...(profiles ?? [])].sort((a, b) => Number(archived(a)) - Number(archived(b)) || Number(a.key === AD_HOC) - Number(b.key === AD_HOC) || a.name.localeCompare(b.name))
  const own = ordered.filter((p) => p.key !== AD_HOC)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Procesos</h1>
          <p className="text-muted-foreground">
            Cada proceso define qué documentos se piden y qué se comprueba antes de decidir. Los cambios se preparan sin afectar a nadie y se aplican al
            publicarlos.
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
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {ordered.map((p) => (
            <ProcessCard key={p.key} profile={p} cases={count(p.key)} />
          ))}
          {isAdmin() && (
            <Link
              to="/profiles/new"
              className="flex min-h-48 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
            >
              <Plus className="size-6" />
              <span className="font-medium">{own.length ? 'Nuevo proceso' : 'Crea tu primer proceso'}</span>
              <span className="text-sm">Qué documentos pides y qué se comprueba antes de decidir.</span>
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
