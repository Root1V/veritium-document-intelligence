// How Risk and Legal read a case (VRT-45): each lens that applies, its
// latest reading, and every statement's evidence — a click opens the
// document on that page with the box.
import { Link } from 'react-router-dom'
import { CircleAlert, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { errorDetail } from '@/lib/apiErrors'
import { canExecute } from '@/lib/auth'
import { cn } from '@/lib/utils'
import { useCaseLenses, useReadWithLens } from '@/lib/queries'
import type { CaseLens, LensEvidence, LensOutput } from '@/types/api'

const AREA = { riesgos: 'Riesgos', legal: 'Legal' } as const
const STATUS = {
  cumple: { label: 'Cumple', dot: 'bg-emerald-500' },
  no_cumple: { label: 'No cumple', dot: 'bg-red-500' },
  no_encontrado: { label: 'No lo menciona', dot: 'bg-red-500' },
  dudoso: { label: 'Dudoso', dot: 'bg-amber-500' },
} as const

function Citations({ evidence, onOpen }: { evidence: LensEvidence[]; onOpen: (e: LensEvidence) => void }) {
  if (!evidence.length) return null
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1">
      {evidence.map((e) => (
        <button key={e.ref} type="button" onClick={() => onOpen(e)} className="rounded border px-1 text-[10px] text-muted-foreground hover:bg-muted" title={e.text}>
          {e.document_name.split(' (')[0]} · pág. {e.page + 1}
        </button>
      ))}
    </span>
  )
}

function Reading({ output, onOpen }: { output: LensOutput; onOpen: (e: LensEvidence) => void }) {
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p className="font-medium">{output.headline}</p>
      {output.points.length > 0 && (
        <ul className="flex list-disc flex-col gap-1 pl-5">
          {output.points.map((p, i) => (
            <li key={i}>
              {p.text}
              <Citations evidence={p.evidence} onOpen={onOpen} />
            </li>
          ))}
        </ul>
      )}
      {output.attention.length > 0 && (
        <div className="flex flex-col gap-1 rounded-md border border-amber-500/40 bg-amber-50 p-2 dark:bg-amber-950/30">
          <span className="text-xs font-medium text-amber-800 dark:text-amber-300">Atención</span>
          {output.attention.map((p, i) => (
            <span key={i}>
              {p.text}
              <Citations evidence={p.evidence} onOpen={onOpen} />
            </span>
          ))}
        </div>
      )}
      {output.checks.map((c) => (
        <div key={c.item_key} className="flex flex-col gap-1 border-b pb-2 last:border-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn('size-2.5 rounded-full', STATUS[c.status].dot)} />
            <span className="font-medium">{c.label}</span>
            {c.importance === 'alta' && (
              <Badge variant="outline" className="text-[10px]">
                importante
              </Badge>
            )}
            <span className="ml-auto text-xs font-medium">{STATUS[c.status].label}</span>
          </div>
          <span className="text-muted-foreground">
            {c.explanation}
            <Citations evidence={c.evidence} onOpen={onOpen} />
          </span>
          {c.quote && (
            <span className="text-xs">
              «{c.quote}»{' '}
              {c.quote_verified === false && <span className="text-destructive">— esta cita no aparece en el documento; verifícala.</span>}
            </span>
          )}
        </div>
      ))}
      {(output.truncated || output.unknown_refs > 0) && (
        <span className="text-xs text-muted-foreground">
          {output.truncated && 'Los documentos eran largos: se leyó una parte. '}
          {output.unknown_refs > 0 && `Se descartaron ${output.unknown_refs} citas que no correspondían a ningún texto.`}
        </span>
      )}
    </div>
  )
}

function LensBlock({ caseId, item, onOpen }: { caseId: string; item: CaseLens; onOpen: (e: LensEvidence) => void }) {
  const read = useReadWithLens()
  const latest = item.latest
  const running = latest?.status === 'running' || read.isPending
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{AREA[item.lens.area]}</Badge>
        <span className="font-medium">{item.lens.name}</span>
        {canExecute() && (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={running}
            onClick={() => read.mutate({ caseId, key: item.lens.key }, { onError: (e) => toast.error(errorDetail(e)) })}
          >
            {running && <Loader2 className="size-3.5 animate-spin" />}
            {running ? 'Leyendo…' : latest ? 'Volver a leer' : 'Leer'}
          </Button>
        )}
      </div>
      <span className="text-xs text-muted-foreground">{item.lens.description}</span>
      {latest?.status === 'failed' && <span className="text-sm text-destructive">No se pudo leer: {latest.error}</span>}
      {latest?.status === 'done' && latest.output && (
        <>
          {latest.outdated && (
            <span className="flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400">
              <CircleAlert className="size-3.5" /> La lente cambió después de esta lectura; vuelve a leer para aplicar la versión actual.
            </span>
          )}
          <Reading output={latest.output} onOpen={onOpen} />
          <span className="text-xs text-muted-foreground">
            Leído el {new Date(latest.created_at).toLocaleString()} por {latest.created_by}. Es un análisis automático: confirma lo importante en el documento.
          </span>
        </>
      )}
    </div>
  )
}

export function LensesCard({ caseId, onEvidence }: { caseId: string; onEvidence: (e: LensEvidence) => void }) {
  const { data: lenses } = useCaseLenses(caseId)
  const applicable = (lenses ?? []).filter((l) => l.applicable)
  if (!lenses) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>Lectura para Riesgos y Legal</CardTitle>
        <CardDescription>
          Un resumen para Riesgos y la revisión de cláusulas que pide Legal, con la cita de dónde lo dice cada documento.{' '}
          <Link to="/lenses" className="underline">
            Ver o editar las lentes
          </Link>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {applicable.length === 0 && <span className="text-sm text-muted-foreground">Ninguna lente aplica a los documentos de este expediente.</span>}
        {applicable.map((item) => (
          <LensBlock key={item.lens.key} caseId={caseId} item={item} onOpen={onEvidence} />
        ))}
      </CardContent>
    </Card>
  )
}
