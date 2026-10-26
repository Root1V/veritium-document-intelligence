import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CircleCheck, Loader2, Pencil, Plus, Sparkles, X } from 'lucide-react'
import { toast } from 'sonner'
import { useResolveTypeSuggestion, useTypeSuggestions, useUpdateTypeSuggestion } from '@/lib/queries'
import { canExecute } from '@/lib/auth'
import { DeleteButton } from '@/components/DeleteButton'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { SuggestedFieldType, TypeSuggestion } from '@/types/api'

const FIELD_TYPES: SuggestedFieldType[] = ['str', 'int', 'float', 'bool', 'list']
// Each kind of datum as a person says it (VRT-108).
const FIELD_TYPE_LABEL: Record<string, string> = { str: 'texto', int: 'número entero', float: 'número', bool: 'sí / no', list: 'lista' }

// SuggestedField (the GET response shape) types field_type as plain
// `string` since it's read-only there; editing needs the narrower literal
// union so the type <Select> below is exhaustive.
interface EditableField {
  name: string
  field_type: SuggestedFieldType
  description: string
  required: boolean
}

function emptyField(): EditableField {
  return { name: '', field_type: 'str', description: '', required: true }
}

function SuggestionCard({ suggestion, canResolve }: { suggestion: TypeSuggestion; canResolve: boolean }) {
  const resolve = useResolveTypeSuggestion()
  const update = useUpdateTypeSuggestion()
  const [isEditing, setIsEditing] = useState(false)
  const [typeName, setTypeName] = useState(suggestion.suggested_type_name)
  const [displayName, setDisplayName] = useState(suggestion.suggested_display_name)
  const [fields, setFields] = useState<EditableField[]>(suggestion.fields as EditableField[])

  const names = fields.map((f) => f.name.trim())
  const hasBlankName = names.some((n) => !n)
  const hasDuplicateName = new Set(names).size !== names.length
  const isTypeNameValid = /^[a-z][a-z0-9_]*$/.test(typeName)
  const canSave = !hasBlankName && !hasDuplicateName && isTypeNameValid && displayName.trim().length > 0

  function startEditing() {
    setTypeName(suggestion.suggested_type_name)
    setDisplayName(suggestion.suggested_display_name)
    setFields(suggestion.fields as EditableField[])
    setIsEditing(true)
  }

  function updateField(index: number, patch: Partial<EditableField>) {
    setFields((prev) => prev.map((f, i) => (i === index ? { ...f, ...patch } : f)))
  }

  function removeField(index: number) {
    setFields((prev) => prev.filter((_, i) => i !== index))
  }

  function handleSave() {
    update.mutate(
      {
        suggestionId: suggestion.id,
        body: { suggested_type_name: typeName, suggested_display_name: displayName, fields },
      },
      {
        onSuccess: () => {
          toast.success('Propuesta actualizada.')
          setIsEditing(false)
        },
        onError: () => toast.error('No se pudo guardar — revisa nombres de campo y del tipo.'),
      },
    )
  }

  function handleResolve(decision: 'accept' | 'reject') {
    resolve.mutate(
      { suggestionId: suggestion.id, decision },
      {
        onSuccess: () => toast.success(decision === 'accept' ? 'Sugerencia aceptada.' : 'Sugerencia rechazada.'),
        onError: () => toast.error('No se pudo procesar la decisión.'),
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          {isEditing ? (
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="h-8 max-w-xs" />
          ) : (
            <CardTitle>{suggestion.suggested_display_name}</CardTitle>
          )}
          {isEditing ? (
            <Input
              value={typeName}
              onChange={(e) => setTypeName(e.target.value)}
              className="h-8 max-w-52 font-mono text-xs"
              placeholder="snake_case"
            />
          ) : (
            <Badge variant="outline" className="font-mono text-xs">
              {suggestion.suggested_type_name}
            </Badge>
          )}
        </div>
        <CardDescription>{suggestion.rationale}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!isEditing ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {suggestion.fields.map((field) => (
              <div key={field.name} className="flex flex-col gap-0.5 rounded-lg border bg-background px-3 py-2">
                <span className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium">{field.name.replace(/_/g, ' ')}</span>
                  <span className="text-xs text-muted-foreground">
                    {FIELD_TYPE_LABEL[field.field_type] ?? field.field_type}
                    {field.required && ' · obligatorio'}
                  </span>
                </span>
                {field.description && <span className="text-xs text-muted-foreground">{field.description}</span>}
              </div>
            ))}
          </div>
        ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Campo</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead>Descripción</TableHead>
                <TableHead>Obligatorio</TableHead>
                <TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {fields.map((field, index) => (
                  <TableRow key={index}>
                    <TableCell>
                      <Input
                        value={field.name}
                        onChange={(e) => updateField(index, { name: e.target.value })}
                        className="h-8 font-mono text-xs"
                      />
                    </TableCell>
                    <TableCell>
                      <Select value={field.field_type} onValueChange={(v) => updateField(index, { field_type: v as SuggestedFieldType })}>
                        <SelectTrigger className="h-8 w-32 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {FIELD_TYPES.map((t) => (
                            <SelectItem key={t} value={t}>
                              {FIELD_TYPE_LABEL[t]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Input value={field.description} onChange={(e) => updateField(index, { description: e.target.value })} className="h-8 text-xs" />
                    </TableCell>
                    <TableCell>
                      <input
                        type="checkbox"
                        checked={field.required}
                        onChange={(e) => updateField(index, { required: e.target.checked })}
                        className="size-4 rounded border-input"
                      />
                    </TableCell>
                    <TableCell>
                      <Button type="button" size="icon" variant="ghost" className="size-7" onClick={() => removeField(index)}>
                        <X className="size-3.5" />
                      </Button>
                    </TableCell>
                  </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        )}

        {isEditing && (
          <div className="flex flex-col gap-2">
            <Button type="button" size="sm" variant="outline" className="self-start" onClick={() => setFields((prev) => [...prev, emptyField()])}>
              <Plus className="size-3.5" />
              Agregar campo
            </Button>
            {(hasBlankName || hasDuplicateName || !isTypeNameValid || !displayName.trim()) && (
              <p className="text-xs text-destructive">
                {hasBlankName && 'Todos los campos necesitan un nombre. '}
                {hasDuplicateName && 'Hay nombres de campo repetidos. '}
                {!isTypeNameValid && 'El nombre del tipo debe ser snake_case (ej. debt_capacity_calculation). '}
                {!displayName.trim() && 'El nombre visible no puede estar vacío.'}
              </p>
            )}
          </div>
        )}

        {canResolve && (
          <div className="flex gap-2">
            {isEditing ? (
              <>
                <Button size="sm" disabled={!canSave || update.isPending} onClick={handleSave}>
                  {update.isPending && <Loader2 className="size-3.5 animate-spin" />}
                  Guardar
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setIsEditing(false)}>
                  Cancelar
                </Button>
              </>
            ) : (
              <>
                <Button size="sm" disabled={resolve.isPending} onClick={() => handleResolve('accept')}>
                  Aceptar
                </Button>
                <Button size="sm" variant="outline" disabled={resolve.isPending} onClick={() => handleResolve('reject')}>
                  Rechazar
                </Button>
                <Button size="sm" variant="ghost" onClick={startEditing}>
                  <Pencil className="size-3.5" />
                  Editar
                </Button>
                <DeleteButton
                  className="ml-auto"
                  path={`/type-suggestions/${suggestion.id}`}
                  question="Se eliminará para siempre esta sugerencia. El documento que la originó no cambia."
                />
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function TypeSuggestionsPage() {
  const { data: suggestions, isLoading } = useTypeSuggestions()
  const canResolve = canExecute()

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Tipos de documento nuevos</h1>
        <p className="max-w-3xl text-muted-foreground">
          Documentos que no se parecen a ningún tipo conocido: Veritium propone un tipo nuevo con sus datos. Ajústalo si hace falta y acéptalo; el equipo de
          plataforma lo registra después en Tipos de documento.
        </p>
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : !suggestions || suggestions.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border-2 border-dashed py-14 text-center">
          <CircleCheck className="size-10 text-emerald-600" />
          <span className="text-lg font-medium">Ninguna propuesta pendiente</span>
          <span className="max-w-md text-sm text-muted-foreground">
            Aparecen aquí cuando llega un documento que no se parece a ningún tipo conocido. Los tipos ya registrados están en{' '}
            <Link to="/document-types" className="text-primary hover:underline">
              Tipos de documento
            </Link>
            .
          </span>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {suggestions.map((suggestion) => (
            <SuggestionCard key={suggestion.id} suggestion={suggestion} canResolve={canResolve} />
          ))}
        </div>
      )}
    </div>
  )
}
