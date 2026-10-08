import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { AlertTriangle, Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useProposeDocumentType, useRegisterDocumentType } from '@/lib/queries'
import type { DocumentTypeDefinition, FieldSpec, FieldSpecType, TypeProposal } from '@/types/api'

const LEAF_TYPES: FieldSpecType[] = ['str', 'int', 'float', 'bool', 'enum']

function errorDetail(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (Array.isArray(detail)) return detail.map((d) => (typeof d === 'string' ? d : d.msg)).join(' · ')
    if (typeof detail === 'string') return detail
  }
  return 'No se pudo completar la operación.'
}

function FieldRow({
  field,
  onChange,
  onRemove,
  nested = false,
}: {
  field: FieldSpec
  onChange: (field: FieldSpec) => void
  onRemove: () => void
  nested?: boolean
}) {
  const types = nested ? LEAF_TYPES : [...LEAF_TYPES, 'list' as FieldSpecType]
  function setType(type: FieldSpecType) {
    onChange({
      ...field,
      type,
      required: type === 'list' ? false : field.required,
      enum_values: type === 'enum' ? (field.enum_values ?? []) : null,
      item_name: type === 'list' ? (field.item_name ?? 'Item') : null,
      items: type === 'list' ? (field.items ?? [{ name: 'value', type: 'str', required: true, description: '' }]) : null,
    })
  }
  return (
    <div className={nested ? 'flex flex-col gap-2 border-l-2 pl-3' : 'flex flex-col gap-2 rounded-lg border p-3'}>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_120px_110px_auto]">
        <Input value={field.name} onChange={(e) => onChange({ ...field, name: e.target.value })} className="font-mono text-xs" aria-label="Nombre del campo" />
        <Select value={field.type} onValueChange={(v) => setType(v as FieldSpecType)}>
          <SelectTrigger aria-label="Tipo de dato">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {types.map((t) => (
              <SelectItem key={t} value={t}>
                {t}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={field.required}
            disabled={field.type === 'list'}
            onChange={(e) => onChange({ ...field, required: e.target.checked })}
          />
          Obligatorio
        </label>
        <Button variant="ghost" size="icon" onClick={onRemove} aria-label="Quitar campo">
          <Trash2 className="size-4" />
        </Button>
      </div>
      <Input
        value={field.description ?? ''}
        onChange={(e) => onChange({ ...field, description: e.target.value })}
        placeholder="Qué es el campo y dónde aparece (lo lee el agente de extracción)"
        className="text-xs"
      />
      {field.type === 'enum' && (
        <Input
          value={(field.enum_values ?? []).join(', ')}
          onChange={(e) => onChange({ ...field, enum_values: e.target.value.split(',').map((v) => v.trim()).filter(Boolean) })}
          placeholder="Valores posibles, separados por coma"
          className="text-xs"
        />
      )}
      {field.type === 'list' && (
        <div className="flex flex-col gap-2">
          <Input
            value={field.item_name ?? ''}
            onChange={(e) => onChange({ ...field, item_name: e.target.value })}
            placeholder="Nombre de cada elemento (CamelCase)"
            className="font-mono text-xs"
          />
          {(field.items ?? []).map((item, i) => (
            <FieldRow
              key={i}
              nested
              field={item}
              onChange={(next) => onChange({ ...field, items: (field.items ?? []).map((it, j) => (j === i ? next : it)) })}
              onRemove={() => onChange({ ...field, items: (field.items ?? []).filter((_, j) => j !== i) })}
            />
          ))}
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => onChange({ ...field, items: [...(field.items ?? []), { name: '', type: 'str', required: false, description: '' }] })}
          >
            <Plus className="size-3.5" /> Campo del elemento
          </Button>
        </div>
      )}
    </div>
  )
}

export function NewDocumentTypePage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const documentId = params.get('document_id') ?? undefined
  const suggestionId = params.get('suggestion_id') ?? undefined
  const [file, setFile] = useState<File | undefined>()
  const [nameHint, setNameHint] = useState(params.get('name') ?? '')
  const [proposal, setProposal] = useState<TypeProposal | undefined>()
  const [definition, setDefinition] = useState<DocumentTypeDefinition | undefined>()
  const [acceptedMappings, setAcceptedMappings] = useState<Set<number>>(new Set())
  const propose = useProposeDocumentType()
  const register = useRegisterDocumentType()

  function handlePropose() {
    if (!file && !documentId) {
      toast.error('Elige un documento de ejemplo.')
      return
    }
    propose.mutate(
      { file, documentId, nameHint: nameHint.trim() || undefined },
      {
        onSuccess: (data) => {
          setProposal(data)
          setDefinition(data.definition)
          setAcceptedMappings(new Set(data.mappings.map((_, i) => i)))
        },
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  function handleRegister() {
    if (!definition || !proposal) return
    register.mutate(
      { definition, mappings: proposal.mappings.filter((_, i) => acceptedMappings.has(i)), suggestion_id: suggestionId ?? null },
      {
        onSuccess: () => {
          toast.success(`Tipo '${definition.display_name}' registrado y publicado.`)
          navigate('/document-types')
        },
        onError: (error) => toast.error(errorDetail(error)),
      },
    )
  }

  const setField = (i: number, field: FieldSpec) =>
    definition && setDefinition({ ...definition, fields: definition.fields.map((f, j) => (j === i ? field : f)) })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Nuevo tipo desde un ejemplo</h1>
        <p className="text-muted-foreground">
          El modelo lee un documento de ejemplo y propone el tipo completo: campos, textos para el clasificador y el agente,
          y qué campos corresponden a atributos del catálogo semántico. Revísalo y edítalo antes de registrarlo.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Documento de ejemplo</CardTitle>
          <CardDescription>
            {documentId ? 'Se usa el documento de la sugerencia aceptada.' : 'PDF o imagen de un documento de la clase que quieres registrar.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {!documentId && <Input type="file" accept=".pdf,image/*" onChange={(e) => setFile(e.target.files?.[0])} />}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name-hint">Cómo lo llamas (opcional)</Label>
            <Input id="name-hint" value={nameHint} onChange={(e) => setNameHint(e.target.value)} placeholder="p. ej. Constancia de no adeudo" />
          </div>
          <Button onClick={handlePropose} disabled={propose.isPending} className="self-start">
            {propose.isPending && <Loader2 className="size-4 animate-spin" />}
            {propose.isPending ? 'Leyendo el documento y proponiendo… (30–60 s)' : 'Proponer tipo'}
          </Button>
        </CardContent>
      </Card>

      {proposal && definition && (
        <>
          {(proposal.similar_existing_type || proposal.key_taken || proposal.dropped_mappings.length > 0) && (
            <Card className="border-amber-300 bg-amber-50 dark:bg-amber-950/30">
              <CardContent className="flex flex-col gap-1 pt-6 text-sm">
                {proposal.similar_existing_type && (
                  <p className="flex items-center gap-2">
                    <AlertTriangle className="size-4" /> Se parece al tipo existente <code>{proposal.similar_existing_type}</code>: quizá baste
                    con una versión nueva de ese tipo.
                  </p>
                )}
                {proposal.key_taken && <p>La clave <code>{definition.key}</code> ya existe: cámbiala para registrarlo.</p>}
                {proposal.dropped_mappings.map((m) => (
                  <p key={m}>Mapeo descartado — {m}</p>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Tipo</CardTitle>
              <CardDescription>{proposal.rationale}</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <div className="flex flex-col gap-1.5">
                <Label>Clave</Label>
                <Input value={definition.key} onChange={(e) => setDefinition({ ...definition, key: e.target.value })} className="font-mono" />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Nombre visible</Label>
                <Input value={definition.display_name} onChange={(e) => setDefinition({ ...definition, display_name: e.target.value })} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Nombre del esquema</Label>
                <Input value={definition.schema_title} onChange={(e) => setDefinition({ ...definition, schema_title: e.target.value })} className="font-mono" />
              </div>
              <div className="flex flex-col gap-1.5 md:col-span-3">
                <Label>Descripción (la lee el clasificador)</Label>
                <Textarea value={definition.description} onChange={(e) => setDefinition({ ...definition, description: e.target.value })} />
              </div>
              <div className="flex flex-col gap-1.5 md:col-span-3">
                <Label>Pistas para el agente de extracción</Label>
                <Textarea value={definition.extraction_hint} onChange={(e) => setDefinition({ ...definition, extraction_hint: e.target.value })} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Campos ({definition.fields.length})</CardTitle>
              <CardDescription>Nombres en snake_case. Una lista es para tablas o elementos repetidos.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {definition.fields.map((field, i) => (
                <FieldRow
                  key={i}
                  field={field}
                  onChange={(next) => setField(i, next)}
                  onRemove={() => setDefinition({ ...definition, fields: definition.fields.filter((_, j) => j !== i) })}
                />
              ))}
              <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => setDefinition({ ...definition, fields: [...definition.fields, { name: '', type: 'str', required: false, description: '' }] })}
              >
                <Plus className="size-3.5" /> Agregar campo
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Mapeos al catálogo semántico</CardTitle>
              <CardDescription>
                Los marcados se publican en una versión nueva del catálogo, junto con el tipo. Si renombras un campo, desmarca su mapeo.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {proposal.mappings.length === 0 && <p className="text-sm text-muted-foreground">Sin mapeos propuestos.</p>}
              {proposal.mappings.map((m, i) => (
                <label key={`${m.field_path}-${m.attribute}`} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={acceptedMappings.has(i)}
                    onChange={(e) => {
                      const next = new Set(acceptedMappings)
                      if (e.target.checked) next.add(i)
                      else next.delete(i)
                      setAcceptedMappings(next)
                    }}
                  />
                  <code>{m.field_path}</code> → <Badge variant="secondary">{m.attribute}</Badge>
                  <span className="text-muted-foreground">rol {m.role}</span>
                </label>
              ))}
            </CardContent>
          </Card>

          <Button onClick={handleRegister} disabled={register.isPending} className="self-start">
            {register.isPending && <Loader2 className="size-4 animate-spin" />}
            Registrar y publicar
          </Button>
        </>
      )}
    </div>
  )
}
