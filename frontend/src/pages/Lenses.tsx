// The lenses Risk and Legal read cases with (VRT-45). Legal keeps its
// playbook here — what each document must say — and Risk what its summary
// should focus on. Only an admin edits; a reading done before an edit is
// marked as outdated on the case.
import { useMemo, useState } from 'react'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { errorDetail } from '@/lib/apiErrors'
import { isAdmin } from '@/lib/auth'
import { useDocumentTypeCatalog, useLenses, useSaveLens } from '@/lib/queries'
import type { LensDefinition, PlaybookItem } from '@/types/api'

const AREA = { riesgos: 'Riesgos', legal: 'Legal' } as const
const IMPORTANCE = { alta: 'Importante', media: 'Normal', baja: 'Menor' } as const

function keyFrom(label: string, taken: string[]): string {
  const base =
    label
      .normalize('NFKD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 40) || 'punto'
  const key = /^[a-z]/.test(base) ? base : `p_${base}`
  let n = 1
  let candidate = key
  while (taken.includes(candidate)) candidate = `${key}_${++n}`
  return candidate
}

function LensCard({ lens, typeName }: { lens: LensDefinition; typeName: Record<string, string> }) {
  const save = useSaveLens()
  const [draft, setDraft] = useState<LensDefinition | null>(null)
  const editing = draft !== null
  const shown = draft ?? lens
  const setItem = (i: number, patch: Partial<PlaybookItem>) =>
    setDraft((d) => (d ? { ...d, playbook: d.playbook.map((item, j) => (j === i ? { ...item, ...patch } : item)) } : d))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{AREA[lens.area]}</Badge> {lens.name}
          {isAdmin() && !editing && (
            <Button size="sm" variant="outline" className="ml-auto" onClick={() => setDraft(structuredClone(lens))}>
              Editar
            </Button>
          )}
        </CardTitle>
        <CardDescription>
          {lens.description} Lee: {lens.document_types.length ? lens.document_types.map((t) => typeName[t] ?? t).join(', ') : 'todos los documentos del expediente'}.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {shown.kind === 'summary' ? (
          <div className="flex flex-col gap-1">
            <span className="font-medium">En qué se enfoca el resumen</span>
            {editing ? (
              <Textarea rows={4} value={shown.instructions} onChange={(e) => setDraft({ ...shown, instructions: e.target.value })} />
            ) : (
              <p className="text-muted-foreground">{shown.instructions}</p>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <span className="font-medium">Lo que el documento debe cumplir</span>
            {shown.playbook.map((item, i) =>
              editing ? (
                <div key={item.key} className="flex flex-col gap-1 rounded-md border p-2">
                  <div className="flex gap-2">
                    <Input value={item.label} placeholder="Qué debe cumplirse" onChange={(e) => setItem(i, { label: e.target.value })} />
                    <Select value={item.importance} onValueChange={(v) => setItem(i, { importance: v as PlaybookItem['importance'] })}>
                      <SelectTrigger className="w-36">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {Object.entries(IMPORTANCE).map(([k, v]) => (
                          <SelectItem key={k} value={k}>
                            {v}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label="Quitar"
                      onClick={() => setDraft({ ...shown, playbook: shown.playbook.filter((_, j) => j !== i) })}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                  <Input value={item.guidance} placeholder="Cómo saber si cumple (opcional)" onChange={(e) => setItem(i, { guidance: e.target.value })} />
                </div>
              ) : (
                <div key={item.key} className="flex flex-col">
                  <span>
                    {item.label} {item.importance === 'alta' && <Badge variant="outline" className="text-[10px]">importante</Badge>}
                  </span>
                  {item.guidance && <span className="text-xs text-muted-foreground">{item.guidance}</span>}
                </div>
              ),
            )}
            {editing && (
              <Button
                size="sm"
                variant="outline"
                className="w-fit"
                onClick={() =>
                  setDraft({
                    ...shown,
                    playbook: [...shown.playbook, { key: keyFrom(`punto ${shown.playbook.length + 1}`, shown.playbook.map((p) => p.key)), label: '', guidance: '', importance: 'media' }],
                  })
                }
              >
                <Plus className="size-3.5" /> Agregar punto
              </Button>
            )}
          </div>
        )}
        {editing && (
          <div className="flex gap-2">
            <Button
              disabled={save.isPending || (shown.kind === 'playbook' && shown.playbook.some((p) => !p.label.trim()))}
              onClick={() =>
                save.mutate(shown, {
                  onSuccess: () => {
                    setDraft(null)
                    toast.success('Lente guardada. Las próximas lecturas la usan.')
                  },
                  onError: (e) => toast.error(errorDetail(e)),
                })
              }
            >
              {save.isPending && <Loader2 className="size-4 animate-spin" />} Guardar
            </Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>
              Cancelar
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function LensesPage() {
  const { data: lenses, isLoading } = useLenses()
  const { data: types } = useDocumentTypeCatalog()
  const typeName = useMemo(() => Object.fromEntries((types?.registered ?? []).map((t) => [t.name, t.display_name])), [types])

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Lentes de Riesgos y Legal</h1>
        <p className="text-muted-foreground">
          Cómo leen los expedientes las áreas que deciden después: Riesgos recibe un resumen con lo que le importa, y Legal revisa cada documento contra
          lo que debe cumplir. Cada afirmación cita dónde lo dice el documento. Se usan desde la vista de cada expediente.
        </p>
      </div>
      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        (lenses ?? []).map((lens) => <LensCard key={lens.key} lens={lens} typeName={typeName} />)
      )}
    </div>
  )
}
