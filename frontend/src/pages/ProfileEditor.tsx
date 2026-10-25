// The process editor (VRT-37, VRT-80, VRT-87): what the process asks for and
// what it checks, beside a live preview of how it will decide. Changes go to
// one draft — saved in place, continued later — and publishing applies them
// to new cases in a single step.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CircleAlert, FileText, Loader2, Plus, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DecisionPreview } from '@/components/profiles/DecisionPreview'
import { Choice, RequirementRow } from '@/components/profiles/RequirementRow'
import { RuleList } from '@/components/profiles/RuleList'
import { errorDetail } from '@/lib/apiErrors'
import { slug, whenOf } from '@/lib/processProfile'
import { useProcessProfiles, useProfileLibrary, useProfileVersion, usePublishProfileVersion, useSaveProfileVersion } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ProcessProfileDefinition, RuleBinding } from '@/types/api'

const SEVERITY_RANK = { info: 0, warning: 1, error: 2 } as const
const RETENTION = [
  { value: 'none', label: 'Sin plazo: se conservan' },
  { value: '30', label: '30 días' },
  { value: '90', label: '90 días' },
  { value: '180', label: '6 meses' },
  { value: '365', label: '1 año' },
  { value: '1825', label: '5 años' },
  { value: 'other', label: 'Otro plazo…' },
]

/** A new version may not bind retired rule ids: each becomes the rule that
 * replaced it, the strictest binding winning when several merge (VRT-35). */
function withCurrentRuleIds(definition: ProcessProfileDefinition, legacy: Record<string, string>): ProcessProfileDefinition {
  const merged = new Map<string, RuleBinding>()
  for (const b of definition.rule_bindings) {
    const rule_id = legacy[b.rule_id] ?? b.rule_id
    const prev = merged.get(rule_id)
    merged.set(
      rule_id,
      prev
        ? {
            rule_id,
            severity: SEVERITY_RANK[b.severity] > SEVERITY_RANK[prev.severity] ? b.severity : prev.severity,
            blocking: prev.blocking || b.blocking,
            on_fail: prev.on_fail === 'return_to_client' || (b.blocking && b.on_fail === 'return_to_client') ? 'return_to_client' : prev.blocking ? prev.on_fail : b.on_fail,
          }
        : { ...b, rule_id },
    )
  }
  return { ...definition, rule_bindings: [...merged.values()] }
}

function emptyDefinition(catalogVersion: number): ProcessProfileDefinition {
  return { semantic_catalog_version: catalogVersion, checklist: [], include_all_rules: false, rule_bindings: [], thresholds: {} }
}

function Section({ number, title, description, children }: { number: number; title: string; description: string; children: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex gap-3">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{number}</span>
          <div className="flex flex-col gap-0.5">
            <h2 className="font-semibold">{title}</h2>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {children}
      </CardContent>
    </Card>
  )
}

export function ProfileEditorPage() {
  const { key: routeKey } = useParams()
  const isNew = !routeKey
  const navigate = useNavigate()
  const { data: profiles } = useProcessProfiles()
  const profile = profiles?.find((p) => p.key === routeKey)
  const pendingDraft = profile?.versions.find((v) => v.status === 'draft')?.version
  // Unpublished changes are continued; the person may start again from what is published.
  const [fromPublished, setFromPublished] = useState(false)
  const sourceVersion = pendingDraft && !fromPublished ? pendingDraft : profile?.active_version
  const { data: source } = useProfileVersion(routeKey, sourceVersion)
  const [edited, setEdited] = useState<ProcessProfileDefinition | undefined>()
  const [savedDraft, setSavedDraft] = useState<number | undefined>()
  const [dirty, setDirty] = useState(false)
  const [name, setName] = useState<string | undefined>()
  const [description, setDescription] = useState<string | undefined>()
  const [key, setKey] = useState('')
  const [customRetention, setCustomRetention] = useState(false)
  const { data: library } = useProfileLibrary(edited?.semantic_catalog_version ?? source?.definition.semantic_catalog_version)
  const save = useSaveProfileVersion()
  const publish = usePublishProfileVersion()
  const draft = savedDraft ?? pendingDraft

  const definition =
    edited ?? (isNew ? (library ? emptyDefinition(library.catalog_version) : undefined) : source && library ? withCurrentRuleIds(source.definition, library.legacy_rule_ids) : undefined)

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const suggestions = useMemo(() => {
    if (!definition || !library) return []
    const types = new Set<string>()
    for (const item of definition.checklist) {
      if (item.document_type) types.add(item.document_type)
      for (const a of item.requires_attributes) for (const p of library.attributes.find((x) => x.key === a)?.providers ?? []) if (p.role === item.role) types.add(p.document_type)
    }
    const bound = new Set(definition.rule_bindings.map((b) => b.rule_id))
    return library.rules
      .filter((r) => !bound.has(r.rule_id))
      .map((r) => ({ rule: r, runsOn: r.applies_to.filter((t) => types.has(t)) }))
      .filter(({ rule, runsOn }) => runsOn.length > 0 || rule.used_by.length > 0)
      .sort((a, b) => b.runsOn.length - a.runsOn.length || b.rule.used_by.length - a.rule.used_by.length)
  }, [definition, library])

  if (!definition || !library || (!isNew && !profile)) return <Loader2 className="size-5 animate-spin text-muted-foreground" />

  const shownName = name ?? profile?.name ?? ''
  const shownDescription = description ?? profile?.description ?? ''
  const profileKey = isNew ? key.trim() : routeKey!
  const latestCatalog = Math.max(...library.catalog_versions)
  const set = (patch: Partial<ProcessProfileDefinition>) => {
    setDirty(true)
    setEdited({ ...definition, ...patch })
  }
  const asked = new Set(definition.checklist.map((c) => c.document_type).filter(Boolean))
  const quickTypes = library.document_types.filter((t) => !asked.has(t.key)).sort((a, b) => b.used_by.length - a.used_by.length).slice(0, 6)
  const retentionValue = customRetention ? 'other' : definition.retention_days == null ? 'none' : RETENTION.some((r) => r.value === String(definition.retention_days)) ? String(definition.retention_days) : 'other'

  // What keeps it from being saved, in the person's words.
  const problems: string[] = []
  if (!shownName.trim()) problems.push('Ponle un nombre al proceso.')
  if (isNew && !profileKey) problems.push('Falta el identificador del proceso.')
  definition.checklist.forEach((c, i) => {
    const n = `Requisito ${i + 1}`
    if (!c.label.trim()) problems.push(`${n}: indica qué se pide.`)
    if (c.document_type != null ? !c.document_type : !c.requires_attributes[0]) problems.push(`${n}: elige ${c.document_type != null ? 'el tipo de documento' : 'el dato'}.`)
    if (whenOf(c) === 'condition' && !c.required_when_cel?.trim()) problems.push(`${n}: escribe la condición.`)
  })
  const keys = definition.checklist.map((c) => c.key).filter(Boolean)
  if (new Set(keys).size < keys.length) problems.push('Dos requisitos tienen el mismo nombre.')
  const renamed = !isNew && (shownName.trim() !== profile?.name || (shownDescription.trim() || null) !== (profile?.description ?? null))
  const changed = dirty || renamed
  const busy = save.isPending || publish.isPending

  function persist(then?: (version: number) => void) {
    if (problems.length) return void toast.error(problems[0])
    const cleaned = { ...definition!, checklist: definition!.checklist.map((c) => ({ ...c, key: c.key || slug(c.label) })) }
    save.mutate(
      {
        key: profileKey,
        isNew: isNew && !profiles?.some((p) => p.key === profileKey),
        renamed,
        name: shownName.trim(),
        description: shownDescription.trim(),
        draft,
        definition: cleaned,
      },
      {
        onSuccess: (row) => {
          setSavedDraft(row.version)
          setDirty(false)
          setName(shownName.trim())
          setDescription(shownDescription.trim())
          if (then) then(row.version)
          else toast.success('Cambios guardados. Aún no afectan a ningún expediente: publícalos cuando estén listos.')
        },
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  function handlePublish() {
    if (problems.length) return void toast.error(problems[0])
    if (!confirm(`¿Publicar «${shownName.trim()}»? Los expedientes nuevos lo usarán desde ahora; los que ya están en curso conservan su versión.`)) return
    const go = (version: number) =>
      publish.mutate(
        { key: profileKey, version },
        {
          onSuccess: () => {
            setDirty(false)
            toast.success('Publicado. Los expedientes nuevos ya usan esta versión.')
            navigate('/profiles')
          },
          onError: (error) => toast.error(errorDetail(error)),
        },
      )
    if (changed || !draft) persist(go)
    else go(draft)
  }

  const status = isNew
    ? 'Proceso nuevo · aún no recibe expedientes'
    : draft
      ? `Cambios sin publicar · la versión ${profile?.active_version ?? '—'} sigue vigente`
      : `Editando a partir de la versión ${profile?.active_version} publicada`

  const actions = (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm">
        <span className={cn('size-2 rounded-full', changed ? 'bg-amber-500' : draft ? 'bg-sky-500' : 'bg-emerald-500')} />
        <span className="text-muted-foreground">{changed ? 'Hay cambios sin guardar' : draft ? 'Borrador guardado, sin publicar' : 'Sin cambios'}</span>
      </div>
      {problems.length > 0 && (
        <div className="flex flex-col gap-1 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs">
          <span className="flex items-center gap-1.5 font-medium text-amber-800 dark:text-amber-300">
            <CircleAlert className="size-3.5" /> Para guardar falta
          </span>
          {problems.slice(0, 4).map((p) => (
            <span key={p} className="text-amber-800/90 dark:text-amber-300/90">
              · {p}
            </span>
          ))}
          {problems.length > 4 && <span className="text-amber-800/90 dark:text-amber-300/90">· y {problems.length - 4} más</span>}
        </div>
      )}
      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={() => persist()} disabled={busy || !changed}>
          {save.isPending && !publish.isPending && <Loader2 className="size-4 animate-spin" />}
          Guardar borrador
        </Button>
        <Button className="flex-1" onClick={handlePublish} disabled={busy || (!changed && !draft)}>
          {publish.isPending && <Loader2 className="size-4 animate-spin" />}
          Publicar
        </Button>
      </div>
    </div>
  )

  const preview = (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5">
        <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Así decidirá</span>
        <DecisionPreview definition={definition} library={library} />
      </CardContent>
    </Card>
  )

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{isNew ? 'Nuevo proceso' : shownName || routeKey}</h1>
        <p className="text-muted-foreground">{status}</p>
        {!isNew && pendingDraft && !fromPublished && !savedDraft && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2 text-sm">
            <span className="flex-1">Continúas los cambios que quedaron sin publicar.</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-7"
              onClick={() => {
                setFromPublished(true)
                setEdited(undefined)
                setDirty(true)
              }}
            >
              <RotateCcw className="size-3.5" /> Empezar desde lo publicado
            </Button>
          </div>
        )}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-start">
        <div className="flex min-w-0 flex-col gap-6">
          <Section number={1} title="El proceso" description="Cómo se llama y cuánto tiempo se guardan los datos personales de sus expedientes.">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="name">Nombre</Label>
                <Input
                  id="name"
                  value={shownName}
                  onChange={(e) => {
                    if (isNew && (!key || key === slug(shownName, '-'))) setKey(slug(e.target.value, '-'))
                    setName(e.target.value)
                  }}
                  placeholder="p. ej. Contratación de tarjetas"
                />
                {isNew && profileKey && <span className="text-xs text-muted-foreground">Identificador para integraciones: <code>{profileKey}</code></span>}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="retention">Conservación de datos personales</Label>
                <div className="flex gap-2">
                  <Choice
                    value={retentionValue}
                    className="flex-1"
                    options={RETENTION}
                    onChange={(v) => {
                      setCustomRetention(v === 'other')
                      if (v !== 'other') set({ retention_days: v === 'none' ? null : Number(v) })
                    }}
                  />
                  {retentionValue === 'other' && (
                    <Input
                      id="retention"
                      type="number"
                      min={1}
                      className="w-28"
                      placeholder="días"
                      value={definition.retention_days ?? ''}
                      onChange={(e) => set({ retention_days: e.target.value ? Number(e.target.value) : null })}
                    />
                  )}
                </div>
                <span className="text-xs text-muted-foreground">Desde la decisión; al vencer, el expediente queda anonimizado. Lo define Legal.</span>
              </div>
              <div className="flex flex-col gap-1.5 md:col-span-2">
                <Label htmlFor="description">Descripción</Label>
                <Input id="description" value={shownDescription} onChange={(e) => setDescription(e.target.value)} placeholder="Para qué se usa, en una frase." />
              </div>
            </div>
            <details className="text-sm">
              <summary className="w-fit cursor-pointer text-muted-foreground select-none hover:text-foreground">Opciones avanzadas</summary>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                {isNew && (
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="key">Identificador</Label>
                    <Input id="key" value={key} onChange={(e) => setKey(e.target.value)} className="font-mono text-xs" />
                    <span className="text-xs text-muted-foreground">Lo usan los sistemas conectados; no cambia después.</span>
                  </div>
                )}
                <div className="flex flex-col gap-1.5">
                  <Label>Versión del catálogo de datos</Label>
                  <Choice
                    value={String(definition.semantic_catalog_version)}
                    options={library.catalog_versions.map((v) => ({ value: String(v), label: `Versión ${v}${v === latestCatalog ? ' (la más reciente)' : ''}` }))}
                    onChange={(v) => set({ semantic_catalog_version: Number(v) })}
                  />
                  {definition.semantic_catalog_version < latestCatalog && (
                    <span className="text-xs text-amber-700 dark:text-amber-400">Hay una versión más nueva del catálogo (la {latestCatalog}).</span>
                  )}
                </div>
              </div>
            </details>
          </Section>

          <Section
            number={2}
            title={`Qué documentos pide${definition.checklist.length ? ` (${definition.checklist.length})` : ''}`}
            description="Un tipo de documento concreto, o un dato —como el ingreso del titular— que cumple cualquier documento que lo traiga."
          >
            {definition.checklist.length === 0 && (
              <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">Aún no pide documentos. Agrega el primero o elige uno de los más usados.</p>
            )}
            {definition.checklist.map((item, i) => (
              <RequirementRow
                key={i}
                index={i}
                item={item}
                library={library}
                onChange={(next) => set({ checklist: definition.checklist.map((x, j) => (j === i ? next : x)) })}
                onRemove={() => set({ checklist: definition.checklist.filter((_, j) => j !== i) })}
              />
            ))}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => set({ checklist: [...definition.checklist, { key: '', label: '', document_type: '', requires_attributes: [], role: 'titular', required: true, min_count: 1 }] })}
              >
                <Plus className="size-3.5" /> Agregar requisito
              </Button>
              {quickTypes.length > 0 && <span className="text-xs text-muted-foreground">o rápido:</span>}
              {quickTypes.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() =>
                    set({ checklist: [...definition.checklist, { key: slug(t.display_name), label: t.display_name, document_type: t.key, requires_attributes: [], role: 'titular', required: true, min_count: 1 }] })
                  }
                  className="inline-flex items-center gap-1 rounded-full border border-dashed px-2.5 py-1 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                >
                  <FileText className="size-3" /> {t.display_name}
                </button>
              ))}
            </div>
          </Section>

          <Section
            number={3}
            title={`Qué comprueba${definition.rule_bindings.length ? ` (${definition.rule_bindings.length})` : ''}`}
            description="Las comprobaciones que se hacen y qué pasa con el expediente si una falla."
          >
            <label className="flex items-start gap-3 rounded-lg border bg-muted/30 p-3 text-sm">
              <input type="checkbox" className="mt-0.5 size-4" checked={definition.include_all_rules} onChange={(e) => set({ include_all_rules: e.target.checked })} />
              <span className="flex flex-col gap-0.5">
                <span className="font-medium">Usar también todas las demás reglas activas</span>
                <span className="text-xs text-muted-foreground">Dejan observaciones sin decidir el veredicto. Útil al empezar, antes de elegir qué comprobar.</span>
              </span>
            </label>
            <RuleList bindings={definition.rule_bindings} library={library} suggested={suggestions} onChange={(rule_bindings) => set({ rule_bindings })} />
          </Section>

          <div className="xl:hidden">{preview}</div>
        </div>

        <aside className="hidden flex-col gap-4 xl:sticky xl:top-20 xl:flex">
          <Card>
            <CardContent className="p-5">{actions}</CardContent>
          </Card>
          {preview}
        </aside>
      </div>

      <div className="sticky bottom-0 z-20 -mx-8 -mb-6 flex flex-wrap items-center gap-3 border-t bg-background/95 py-3 pr-24 pl-8 backdrop-blur xl:hidden">
        <span className="flex flex-1 items-center gap-2 text-sm text-muted-foreground">
          <span className={cn('size-2 shrink-0 rounded-full', problems.length ? 'bg-amber-500' : changed ? 'bg-amber-500' : draft ? 'bg-sky-500' : 'bg-emerald-500')} />
          {problems.length ? `Para guardar: ${problems[0]}${problems.length > 1 ? ` (y ${problems.length - 1} más)` : ''}` : changed ? 'Hay cambios sin guardar' : draft ? 'Borrador guardado, sin publicar' : 'Sin cambios'}
        </span>
        <Button variant="outline" onClick={() => persist()} disabled={busy || !changed}>
          Guardar borrador
        </Button>
        <Button onClick={handlePublish} disabled={busy || (!changed && !draft)}>
          Publicar
        </Button>
      </div>
    </div>
  )
}
