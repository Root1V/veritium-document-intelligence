// The readings Risk and Legal make of a case (VRT-45, VRT-91), one block per
// area: Risk's summaries say what they focus on, Legal's reviews each point
// a document must meet, with its importance. The platform team creates and
// edits them in a dialog; a reading done before an edit is marked outdated
// on the case.
import { useState } from 'react'
import { FileText, Gauge, Loader2, Pencil, Plus, Scale, type LucideIcon } from 'lucide-react'
import { SharedConfigNote } from '@/components/layout/SharedConfigNote'
import { LensDialog } from '@/components/lenses/LensDialog'
import { isPlatformAdmin } from '@/lib/auth'
import { AREA, IMPORTANCE } from '@/lib/lenses'
import { useDocumentTypeCatalog, useLenses } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { LensDefinition } from '@/types/api'

const AREA_ICON: Record<LensDefinition['area'], LucideIcon> = { riesgos: Gauge, legal: Scale }

function LensCard({ lens, typeName, onOpen }: { lens: LensDefinition; typeName: (key: string) => string; onOpen?: () => void }) {
  const important = lens.playbook.filter((p) => p.importance === 'alta').length
  return (
    <div className={cn('group flex flex-col gap-4 rounded-xl border bg-card p-5', onOpen && 'cursor-pointer transition hover:border-primary/40 hover:shadow-sm')} onClick={onOpen}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="font-semibold group-hover:underline">{lens.name}</span>
          {lens.description && <p className="text-sm text-muted-foreground">{lens.description}</p>}
        </div>
        {onOpen && <Pencil className="mt-1 size-3.5 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-muted-foreground">Lee</span>
        {lens.document_types.length ? (
          lens.document_types.map((t) => (
            <span key={t} className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-0.5 font-medium text-primary">
              <FileText className="size-3" /> {typeName(t)}
            </span>
          ))
        ) : (
          <span className="rounded-md bg-primary/10 px-2 py-0.5 font-medium text-primary">Todo el expediente</span>
        )}
      </div>

      {lens.kind === 'summary' ? (
        <div className="flex flex-col gap-1 rounded-lg bg-muted/50 px-3 py-2.5 text-sm">
          <span className="text-xs font-medium text-muted-foreground">En qué se enfoca el resumen</span>
          <p>{lens.instructions}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-muted-foreground">Lo que el documento debe cumplir</span>
          <ol className="flex flex-col gap-2 text-sm">
            {lens.playbook.map((p) => (
              <li key={p.key} className="flex items-start gap-2.5">
                <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', IMPORTANCE[p.importance].dot)} title={IMPORTANCE[p.importance].label} />
                <span className="flex flex-col">
                  <span>{p.label}</span>
                  {p.guidance && <span className="text-xs text-muted-foreground">{p.guidance}</span>}
                </span>
              </li>
            ))}
          </ol>
          <span className="mt-1 border-t pt-2 text-xs text-muted-foreground">
            {lens.playbook.length} puntos{important > 0 && ` · ${important === 1 ? '1 importante' : `${important} importantes`}`}
          </span>
        </div>
      )}
    </div>
  )
}

export function LensesPage() {
  const admin = isPlatformAdmin()
  const { data: lenses, isLoading, isError } = useLenses()
  const { data: types } = useDocumentTypeCatalog()
  const [editing, setEditing] = useState<{ lens: LensDefinition | null; area: LensDefinition['area'] } | null>(null)
  const typeName = (key: string) => types?.registered.find((t) => t.name === key)?.display_name ?? key

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Riesgos y Legal</h1>
        <p className="text-muted-foreground">
          Lo que cada área recibe al leer un expediente. Se piden desde la vista del expediente, y cada afirmación cita dónde lo dice el documento.
        </p>
      </div>
      <SharedConfigNote show={!admin} />

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar las lecturas: el servidor de Veritium no responde.</p>
      ) : (
        (Object.keys(AREA) as LensDefinition['area'][]).map((area) => {
          const Icon = AREA_ICON[area]
          const list = (lenses ?? []).filter((l) => l.area === area)
          return (
            <section key={area} className="rounded-2xl border bg-muted/40">
              <div className="flex flex-wrap items-center gap-3 rounded-t-2xl border-b bg-background px-4 py-3 sm:px-5">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                  <Icon className="size-5" />
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-xl font-semibold tracking-tight">{AREA[area].name}</h2>
                    <span className="rounded-full bg-background px-2 py-0.5 text-xs font-medium text-muted-foreground ring-1 ring-border">
                      {list.length === 1 ? '1 lectura' : `${list.length} lecturas`}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground">{AREA[area].hint}</p>
                </div>
                {area === 'legal' && (
                  <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                    {Object.values(IMPORTANCE).map((i) => (
                      <span key={i.label} className="inline-flex items-center gap-1.5">
                        <span className={cn('size-2 rounded-full', i.dot)} /> {i.label}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-2">
                {list.map((lens) => (
                  <LensCard key={lens.key} lens={lens} typeName={typeName} onOpen={admin ? () => setEditing({ lens, area }) : undefined} />
                ))}
                {admin ? (
                  <button
                    type="button"
                    onClick={() => setEditing({ lens: null, area })}
                    className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center text-sm text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                  >
                    <Plus className="size-5" />
                    <span className="font-medium">Nueva lectura para {AREA[area].name}</span>
                    <span className="text-xs">{area === 'legal' ? 'Una revisión punto por punto de un documento.' : 'Un resumen del expediente enfocado en lo que importa.'}</span>
                  </button>
                ) : (
                  !list.length && <p className="text-sm text-muted-foreground">{AREA[area].name} aún no tiene lecturas.</p>
                )}
              </div>
            </section>
          )
        })
      )}

      {editing && (
        <LensDialog
          lens={editing.lens}
          area={editing.area}
          taken={(lenses ?? []).map((l) => l.key)}
          types={types?.registered ?? []}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
