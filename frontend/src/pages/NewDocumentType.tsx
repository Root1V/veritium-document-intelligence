// A new document type from an example (VRT-33, VRT-88), in three steps:
// drop the example, review what Veritium proposes — each datum by its name,
// with its format and what it means — and register it. The technical side
// (keys, schema name, reading hints) stays folded.
import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Check, CircleAlert, FileSearch, Loader2, Plus, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { FieldEditor, type Meaning } from '@/components/documentTypes/FieldEditor'
import { Dropzone } from '@/components/upload/Dropzone'
import { errorDetail } from '@/lib/apiErrors'
import { useDocumentTypeCatalog, useProposeDocumentType, useRegisterDocumentType, useSemanticCatalog } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { DocumentTypeDefinition, FieldSpec, TypeProposal } from '@/types/api'

const SNAKE = /^[a-z][a-z0-9_]*$/
const normalized = (path: string) => path.replace(/\[\d*\]/g, '[]')
const pathsOf = (fields: FieldSpec[]) => new Set(fields.flatMap((f) => [f.name, ...(f.items ?? []).map((i) => `${f.name}[].${i.name}`)]))

function Steps({ current }: { current: 1 | 2 | 3 }) {
  const steps = ['Sube un ejemplo', 'Revisa la propuesta', 'Regístralo']
  return (
    <ol className="flex flex-wrap items-center gap-2 text-sm">
      {steps.map((label, i) => {
        const n = (i + 1) as 1 | 2 | 3
        return (
          <li key={label} className="flex items-center gap-2">
            {i > 0 && <span className="h-px w-6 bg-border" />}
            <span
              className={cn(
                'flex size-6 items-center justify-center rounded-full text-xs font-semibold',
                n < current ? 'bg-emerald-500 text-white' : n === current ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
              )}
            >
              {n < current ? <Check className="size-3.5" /> : n}
            </span>
            <span className={n === current ? 'font-medium' : 'text-muted-foreground'}>{label}</span>
          </li>
        )
      })}
    </ol>
  )
}

function Panel({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-0.5">
          <h2 className="font-semibold">{title}</h2>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        {children}
      </CardContent>
    </Card>
  )
}

/** While the model reads: what it is doing, so 40 seconds do not look like a hang. */
function Reading() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])
  const doing = seconds < 10 ? 'Leyendo el documento' : seconds < 30 ? 'Reconociendo qué datos trae' : 'Proponiendo nombres y significados'
  return (
    <div className="flex items-center gap-3 rounded-lg bg-muted/50 p-4">
      <Loader2 className="size-5 animate-spin text-primary" />
      <div className="flex flex-col">
        <span className="text-sm font-medium">{doing}…</span>
        <span className="text-xs text-muted-foreground">Suele tardar entre 30 y 60 segundos · {seconds} s</span>
      </div>
    </div>
  )
}

export function NewDocumentTypePage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const documentId = params.get('document_id') ?? undefined
  const suggestionId = params.get('suggestion_id') ?? undefined
  const [files, setFiles] = useState<File[]>([])
  const [nameHint, setNameHint] = useState(params.get('name') ?? '')
  const [proposal, setProposal] = useState<TypeProposal | undefined>()
  const [definition, setDefinition] = useState<DocumentTypeDefinition | undefined>()
  const [accepted, setAccepted] = useState<Set<number>>(new Set())
  const propose = useProposeDocumentType()
  const register = useRegisterDocumentType()
  const { data: semantic } = useSemanticCatalog()
  const { data: types } = useDocumentTypeCatalog()

  function handlePropose() {
    if (!files[0] && !documentId) return void toast.error('Elige un documento de ejemplo.')
    propose.mutate(
      { file: files[0], documentId, nameHint: nameHint.trim() || undefined },
      {
        onSuccess: (data) => {
          setProposal(data)
          setDefinition(data.definition)
          setAccepted(new Set(data.mappings.map((_, i) => i)))
        },
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  if (!proposal || !definition) {
    return (
      <div className="flex max-w-3xl flex-col gap-6">
        <div className="flex flex-col gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">Nuevo tipo de documento</h1>
          <Steps current={1} />
        </div>
        <Panel
          title="Sube un documento de ejemplo"
          description="Un PDF o una foto de un documento real de esa clase. Veritium lo lee y te propone qué datos trae, cómo se llaman y qué significan."
        >
          {documentId ? (
            <p className="flex items-center gap-2 rounded-lg bg-muted/50 p-3 text-sm">
              <FileSearch className="size-4 text-muted-foreground" /> Se usará el documento del expediente donde se detectó.
            </p>
          ) : (
            <Dropzone files={files} onChange={(next) => setFiles(next.slice(-1))} />
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name-hint">Cómo lo llamas (opcional)</Label>
            <Input id="name-hint" value={nameHint} onChange={(e) => setNameHint(e.target.value)} placeholder="p. ej. Constancia de no adeudo" />
            <span className="text-xs text-muted-foreground">Ayuda a Veritium a nombrarlo como en tu negocio.</span>
          </div>
          {propose.isPending ? (
            <Reading />
          ) : (
            <Button onClick={handlePropose} disabled={!files[0] && !documentId} className="self-start">
              Leer el ejemplo y proponer
            </Button>
          )}
        </Panel>
      </div>
    )
  }

  const catalog = semantic?.catalog
  const meaningLabel = (attribute: string, role: string) =>
    `${catalog?.attributes.find((a) => a.key === attribute)?.name ?? attribute} · ${(catalog?.roles.find((r) => r.key === role)?.name ?? role).toLowerCase()}`
  const meanings = (path: string): Meaning[] =>
    proposal.mappings
      .map((m, index) => ({ m, index }))
      .filter(({ m }) => normalized(m.field_path) === path)
      .map(({ m, index }) => ({ index, label: meaningLabel(m.attribute, m.role), accepted: accepted.has(index) }))
  const toggle = (index: number) => {
    const next = new Set(accepted)
    if (next.has(index)) next.delete(index)
    else next.add(index)
    setAccepted(next)
  }
  const set = (patch: Partial<DocumentTypeDefinition>) => setDefinition({ ...definition, ...patch })
  const paths = pathsOf(definition.fields)
  const linked = proposal.mappings.filter((m, i) => accepted.has(i) && paths.has(normalized(m.field_path)))
  const allFields = definition.fields.flatMap((f) => [f, ...(f.items ?? [])])

  // What keeps it from being registered, in the person's words.
  const problems: string[] = []
  if (!definition.display_name.trim()) problems.push('Ponle un nombre al documento.')
  if (!SNAKE.test(definition.key)) problems.push('La clave debe ir en minúsculas, sin espacios ni tildes (opciones avanzadas).')
  if (proposal.key_taken && definition.key === proposal.definition.key)
    problems.push(`Ya existe «${types?.registered.find((t) => t.name === definition.key)?.display_name ?? definition.key}»: si es otro documento, cambia la clave en opciones avanzadas.`)
  if (!definition.fields.length) problems.push('Necesita al menos un dato.')
  allFields.forEach((f, i) => {
    const who = f.label?.trim() || `El dato ${i + 1}`
    if (!f.label?.trim()) problems.push(`${who}: ponle un nombre.`)
    if (!SNAKE.test(f.name)) problems.push(`${who}: su nombre técnico debe ir en minúsculas y con guiones bajos.`)
    if (f.type === 'enum' && !f.enum_values?.length) problems.push(`${who}: indica sus opciones.`)
    if (f.type === 'list' && !f.items?.length) problems.push(`${who}: una tabla necesita columnas.`)
  })
  const names = definition.fields.map((f) => f.name)
  if (new Set(names).size < names.length) problems.push('Dos datos tienen el mismo nombre técnico.')

  function handleRegister() {
    if (problems.length) return void toast.error(problems[0])
    register.mutate(
      { definition: definition!, mappings: linked, suggestion_id: suggestionId ?? null },
      {
        onSuccess: () => {
          toast.success(`«${definition!.display_name}» registrado. Veritium ya lo reconoce en los expedientes nuevos.`)
          navigate('/document-types')
        },
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  const startOver = () => {
    setProposal(undefined)
    setDefinition(undefined)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Nuevo tipo de documento</h1>
        <Steps current={2} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px] xl:items-start">
        <div className="flex min-w-0 flex-col gap-6">
          {proposal.similar_existing_type && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-800 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <span>
                Se parece a «{types?.registered.find((t) => t.name === proposal.similar_existing_type)?.display_name ?? proposal.similar_existing_type}», que ya
                existe. Si es el mismo documento, conviene una versión nueva de ese tipo en lugar de uno nuevo.
              </span>
            </div>
          )}

          <Panel title="El documento" description="Cómo se llama y cómo se reconoce entre los demás.">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="display-name">Nombre</Label>
              <Input id="display-name" value={definition.display_name} onChange={(e) => set({ display_name: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="description">Cómo se reconoce</Label>
              <Textarea id="description" value={definition.description} onChange={(e) => set({ description: e.target.value })} className="min-h-20" />
              <span className="text-xs text-muted-foreground">Lo usa Veritium para distinguirlo de los otros tipos: qué es y en qué se diferencia de los parecidos.</span>
            </div>
            <details className="text-sm">
              <summary className="w-fit cursor-pointer text-muted-foreground select-none hover:text-foreground">Opciones avanzadas</summary>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="key">Clave</Label>
                  <Input id="key" value={definition.key} onChange={(e) => set({ key: e.target.value })} className="font-mono text-xs" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="schema">Nombre del esquema</Label>
                  <Input id="schema" value={definition.schema_title} onChange={(e) => set({ schema_title: e.target.value })} className="font-mono text-xs" />
                </div>
                <div className="flex flex-col gap-1.5 md:col-span-2">
                  <Label htmlFor="hint">Pistas para leerlo</Label>
                  <Textarea id="hint" value={definition.extraction_hint} onChange={(e) => set({ extraction_hint: e.target.value })} className="min-h-16 text-xs" />
                </div>
              </div>
            </details>
          </Panel>

          <Panel
            title={`Datos que leerá (${allFields.length})`}
            description="Revisa el nombre de cada dato y si siempre aparece. «Significa» vincula el dato al catálogo, para compararlo con otros documentos; haz clic para quitarlo."
          >
            {definition.fields.map((field, i) => (
              <FieldEditor
                key={i}
                field={field}
                meanings={meanings}
                onToggleMeaning={toggle}
                onChange={(next) => set({ fields: definition.fields.map((f, j) => (j === i ? next : f)) })}
                onRemove={() => set({ fields: definition.fields.filter((_, j) => j !== i) })}
              />
            ))}
            <Button variant="outline" size="sm" className="self-start" onClick={() => set({ fields: [...definition.fields, { name: '', label: '', type: 'str', required: false, description: '' }] })}>
              <Plus className="size-3.5" /> Agregar dato
            </Button>
          </Panel>
        </div>

        <aside className="flex flex-col gap-4 xl:sticky xl:top-20">
          <Card>
            <CardContent className="flex flex-col gap-4 p-5">
              <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Resumen</span>
              <div className="flex flex-col gap-1">
                <span className="font-semibold">{definition.display_name || 'Sin nombre'}</span>
                <span className="text-sm text-muted-foreground">
                  {allFields.length} datos · {allFields.filter((f) => f.required).length} siempre presentes · {linked.length} con significado
                </span>
              </div>
              {proposal.rationale && <p className="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">{proposal.rationale}</p>}
              {proposal.dropped_mappings.length > 0 && (
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">{proposal.dropped_mappings.length} significados descartados por el catálogo</summary>
                  <ul className="mt-1 list-disc pl-4">
                    {proposal.dropped_mappings.map((m) => (
                      <li key={m}>{m}</li>
                    ))}
                  </ul>
                </details>
              )}
              {problems.length > 0 && (
                <div className="flex flex-col gap-1 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-800 dark:text-amber-300">
                  <span className="flex items-center gap-1.5 font-medium">
                    <CircleAlert className="size-3.5" /> Para registrarlo falta
                  </span>
                  {problems.slice(0, 4).map((p) => (
                    <span key={p}>· {p}</span>
                  ))}
                  {problems.length > 4 && <span>· y {problems.length - 4} más</span>}
                </div>
              )}
              <Button onClick={handleRegister} disabled={register.isPending || problems.length > 0}>
                {register.isPending && <Loader2 className="size-4 animate-spin" />}
                Registrar y publicar
              </Button>
              <Button variant="ghost" size="sm" onClick={startOver} disabled={register.isPending}>
                <RotateCcw className="size-3.5" /> Empezar con otro ejemplo
              </Button>
              <p className="text-xs text-muted-foreground">Al registrarlo, Veritium lo reconoce en los expedientes nuevos y sus significados se agregan al catálogo de datos.</p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  )
}
