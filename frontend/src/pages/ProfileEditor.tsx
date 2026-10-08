import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Lightbulb, Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorDetail } from '@/lib/apiErrors'
import { useProcessProfiles, useProfileLibrary, useProfileVersion, usePublishProfileVersion, useSaveProfileVersion } from '@/lib/queries'
import type { ChecklistItem, ProcessProfileDefinition, ProfileLibrary, RuleBinding } from '@/types/api'

const usedBy = (profiles: string[]) => (profiles.length ? ` · usado en ${profiles.join(', ')}` : '')

function Choice({ value, options, onChange, placeholder, width = 'w-56' }: {
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  placeholder?: string
  width?: string
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={`h-8 text-xs ${width}`}>
        <SelectValue placeholder={placeholder ?? '—'} />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function ChecklistRow({ item, library, onChange, onRemove }: {
  item: ChecklistItem
  library: ProfileLibrary
  onChange: (item: ChecklistItem) => void
  onRemove: () => void
}) {
  const byType = item.document_type != null
  const attribute = item.requires_attributes[0] ?? ''
  const providers = library.attributes.find((a) => a.key === attribute)?.providers.filter((p) => p.role === item.role) ?? []
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input value={item.key} onChange={(e) => onChange({ ...item, key: e.target.value })} placeholder="clave" className="h-8 w-40 font-mono text-xs" />
        <Input value={item.label} onChange={(e) => onChange({ ...item, label: e.target.value })} placeholder="Texto para personas" className="h-8 min-w-48 flex-1 text-xs" />
        <Choice
          value={byType ? 'type' : 'attribute'}
          width="w-44"
          options={[
            { value: 'type', label: 'Por tipo de documento' },
            { value: 'attribute', label: 'Por evidencia (atributo)' },
          ]}
          onChange={(v) =>
            onChange(v === 'type' ? { ...item, document_type: '', requires_attributes: [], accepted_document_types: null } : { ...item, document_type: null, requires_attributes: [''] })
          }
        />
        <Button variant="ghost" size="icon" onClick={onRemove} aria-label="Quitar requisito">
          <Trash2 className="size-4" />
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {byType ? (
          <Choice
            value={item.document_type ?? ''}
            placeholder="Tipo de documento"
            width="w-80"
            options={library.document_types.map((t) => ({ value: t.key, label: `${t.display_name}${usedBy(t.used_by)}` }))}
            onChange={(v) => onChange({ ...item, document_type: v })}
          />
        ) : (
          <>
            <Choice
              value={attribute}
              placeholder="Atributo"
              width="w-72"
              options={library.attributes.filter((a) => a.providers.length).map((a) => ({ value: a.key, label: `${a.key}${usedBy(a.used_by)}` }))}
              onChange={(v) => onChange({ ...item, requires_attributes: [v] })}
            />
            <Choice value={item.role} width="w-36" options={library.roles.map((r) => ({ value: r.key, label: r.name }))} onChange={(v) => onChange({ ...item, role: v })} />
            {attribute && (
              <span className="text-xs text-muted-foreground">
                {providers.length ? `lo satisface: ${providers.map((p) => p.document_type).join(', ')}` : 'ningún tipo lo aporta con ese rol'}
              </span>
            )}
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={item.required} onChange={(e) => onChange({ ...item, required: e.target.checked })} /> Obligatorio
        </label>
        <Input
          value={item.required_when_cel ?? ''}
          onChange={(e) => onChange({ ...item, required_when_cel: e.target.value || null })}
          placeholder="Solo si (CEL sobre request/case), p. ej. request.nacionalidad != 'PE'"
          className="h-8 min-w-64 flex-1 font-mono text-xs"
        />
      </div>
    </div>
  )
}

const SEVERITY_RANK = { info: 0, warning: 1, error: 2 } as const

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

export function ProfileEditorPage() {
  const { key: routeKey } = useParams()
  const isNew = !routeKey
  const navigate = useNavigate()
  const { data: profiles } = useProcessProfiles()
  const profile = profiles?.find((p) => p.key === routeKey)
  const { data: activeVersion } = useProfileVersion(routeKey, profile?.active_version)
  const [edited, setDefinition] = useState<ProcessProfileDefinition | undefined>()
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [savedDraft, setSavedDraft] = useState<number | undefined>()
  const { data: library } = useProfileLibrary(edited?.semantic_catalog_version ?? activeVersion?.definition.semantic_catalog_version)
  const save = useSaveProfileVersion()
  const publish = usePublishProfileVersion()
  // Until edited: the active version (a new version of an existing profile), or blank on the latest catalog.
  const definition =
    edited ??
    (isNew ? (library ? emptyDefinition(library.catalog_version) : undefined) : activeVersion && library ? withCurrentRuleIds(activeVersion.definition, library.legacy_rule_ids) : undefined)

  const suggestions = useMemo(() => {
    if (!definition || !library) return []
    const types = new Set<string>()
    for (const item of definition.checklist) {
      if (item.document_type) types.add(item.document_type)
      for (const a of item.requires_attributes) {
        for (const p of library.attributes.find((x) => x.key === a)?.providers ?? []) if (p.role === item.role) types.add(p.document_type)
      }
    }
    const bound = new Set(definition.rule_bindings.map((b) => b.rule_id))
    return library.rules
      .filter((r) => !bound.has(r.rule_id))
      .map((r) => ({ rule: r, runsOn: r.applies_to.filter((t) => types.has(t)) }))
      .filter(({ rule, runsOn }) => runsOn.length > 0 || rule.used_by.length > 0)
      .sort((a, b) => b.runsOn.length - a.runsOn.length || b.rule.used_by.length - a.rule.used_by.length)
  }, [definition, library])

  if (!definition || !library) return <Loader2 className="size-5 animate-spin text-muted-foreground" />

  const set = (patch: Partial<ProcessProfileDefinition>) => {
    setSavedDraft(undefined)
    setDefinition({ ...definition, ...patch })
  }
  const profileKey = isNew ? key.trim() : routeKey!
  const bind = (rule_id: string) => set({ rule_bindings: [...definition.rule_bindings, { rule_id, severity: 'warning', blocking: false, on_fail: 'human_review' }] })
  const setBinding = (i: number, b: RuleBinding) => set({ rule_bindings: definition.rule_bindings.map((x, j) => (j === i ? b : x)) })

  function handleSave() {
    if (isNew && (!profileKey || !name.trim())) {
      toast.error('Indica la clave y el nombre del perfil.')
      return
    }
    save.mutate(
      { key: profileKey, isNew: isNew && !profiles?.some((p) => p.key === profileKey), name: name.trim(), description, definition: definition! },
      {
        onSuccess: (row) => {
          setSavedDraft(row.version)
          toast.success(`Borrador v${row.version} guardado. Publícalo para que lo usen los expedientes nuevos.`)
        },
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  function handlePublish() {
    if (!savedDraft) return
    publish.mutate(
      { key: profileKey, version: savedDraft },
      {
        onSuccess: () => {
          toast.success(`Perfil ${profileKey} v${savedDraft} publicado.`)
          navigate('/profiles')
        },
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  const describe = (ruleId: string) => library.rules.find((r) => r.rule_id === ruleId)
  const latestCatalog = Math.max(...library.catalog_versions)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{isNew ? 'Nuevo perfil de proceso' : `Nueva versión de ${profile?.name ?? routeKey}`}</h1>
        <p className="text-muted-foreground">
          Se arma con lo que ya existe: tipos, atributos y reglas de la biblioteca, con sugerencias de lo que usan otros procesos.{' '}
          <Link to="/profiles" className="underline">
            Volver a perfiles
          </Link>
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Perfil</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          {isNew && (
            <>
              <div className="flex flex-col gap-1">
                <Label>Clave</Label>
                <Input value={key} onChange={(e) => setKey(e.target.value)} placeholder="contratacion-tarjetas" className="w-56 font-mono" />
              </div>
              <div className="flex flex-col gap-1">
                <Label>Nombre</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} className="w-64" />
              </div>
              <div className="flex flex-1 flex-col gap-1">
                <Label>Descripción</Label>
                <Input value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
            </>
          )}
          <div className="flex flex-col gap-1">
            <Label>Catálogo semántico</Label>
            <Choice
              value={String(definition.semantic_catalog_version)}
              width="w-48"
              options={library.catalog_versions.map((v) => ({ value: String(v), label: `v${v}${v === latestCatalog ? ' (última)' : ''}` }))}
              onChange={(v) => set({ semantic_catalog_version: Number(v) })}
            />
          </div>
          {definition.semantic_catalog_version < latestCatalog && (
            <span className="text-xs text-amber-700 dark:text-amber-400">Hay una versión más nueva del catálogo (v{latestCatalog}).</span>
          )}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={definition.include_all_rules} onChange={(e) => set({ include_all_rules: e.target.checked })} />
            Aplicar todas las reglas activas (no solo las vinculadas)
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Requisitos ({definition.checklist.length})</CardTitle>
          <CardDescription>Por tipo de documento, o por evidencia: un atributo que cualquier documento que lo aporte satisface.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {definition.checklist.map((item, i) => (
            <ChecklistRow
              key={i}
              item={item}
              library={library}
              onChange={(next) => set({ checklist: definition.checklist.map((x, j) => (j === i ? next : x)) })}
              onRemove={() => set({ checklist: definition.checklist.filter((_, j) => j !== i) })}
            />
          ))}
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => set({ checklist: [...definition.checklist, { key: '', label: '', document_type: '', requires_attributes: [], role: 'titular', required: true, min_count: 1 }] })}
          >
            <Plus className="size-3.5" /> Requisito
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Reglas vinculadas ({definition.rule_bindings.length})</CardTitle>
          <CardDescription>La severidad y si bloquea la decide el perfil. Una regla que bloquea y falla define el veredicto.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {definition.rule_bindings.map((b, i) => (
            <div key={b.rule_id} className="flex flex-wrap items-center gap-2 text-sm">
              <code className="min-w-72 text-xs">{b.rule_id}</code>
              <Choice value={b.severity} width="w-28" options={['info', 'warning', 'error'].map((v) => ({ value: v, label: v }))} onChange={(v) => setBinding(i, { ...b, severity: v as RuleBinding['severity'] })} />
              <label className="flex items-center gap-1.5 text-xs">
                <input type="checkbox" checked={b.blocking} onChange={(e) => setBinding(i, { ...b, blocking: e.target.checked })} /> Bloquea
              </label>
              {b.blocking && (
                <Choice
                  value={b.on_fail}
                  width="w-48"
                  options={[
                    { value: 'human_review', label: 'Revisión humana' },
                    { value: 'return_to_client', label: 'Devolver al cliente' },
                  ]}
                  onChange={(v) => setBinding(i, { ...b, on_fail: v as RuleBinding['on_fail'] })}
                />
              )}
              <span className="flex-1 truncate text-xs text-muted-foreground">{describe(b.rule_id)?.description ?? 'no está en la biblioteca de este catálogo'}</span>
              <Button variant="ghost" size="icon" onClick={() => set({ rule_bindings: definition.rule_bindings.filter((_, j) => j !== i) })} aria-label="Quitar regla">
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
          <Choice
            value=""
            width="w-96"
            placeholder="Vincular otra regla de la biblioteca…"
            options={library.rules.filter((r) => !definition.rule_bindings.some((b) => b.rule_id === r.rule_id)).map((r) => ({ value: r.rule_id, label: r.rule_id }))}
            onChange={bind}
          />
        </CardContent>
      </Card>

      {suggestions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lightbulb className="size-4" /> Sugerencias de reutilización
            </CardTitle>
            <CardDescription>Reglas que corren sobre los documentos de este perfil o que ya usan otros procesos.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {suggestions.slice(0, 12).map(({ rule, runsOn }) => (
              <div key={rule.rule_id} className="flex flex-wrap items-center gap-2 text-sm">
                <Button variant="outline" size="sm" onClick={() => bind(rule.rule_id)}>
                  <Plus className="size-3.5" /> Vincular
                </Button>
                <code className="text-xs">{rule.rule_id}</code>
                <Badge variant="outline" className="text-[10px]">
                  {rule.kind === 'format' ? 'formato' : rule.kind === 'cel' ? 'regla de negocio' : 'sistema'}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {runsOn.length > 0 && `corre sobre ${runsOn.join(', ')}`}
                  {runsOn.length > 0 && rule.used_by.length > 0 && ' · '}
                  {rule.used_by.length > 0 && `usada en ${rule.used_by.join(', ')}`}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="flex items-center gap-2">
        <Button onClick={handleSave} disabled={save.isPending}>
          {save.isPending && <Loader2 className="size-4 animate-spin" />}
          Guardar borrador
        </Button>
        {savedDraft && (
          <Button onClick={handlePublish} disabled={publish.isPending}>
            Publicar v{savedDraft}
          </Button>
        )}
      </div>
    </div>
  )
}
