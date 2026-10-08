import { useState } from 'react'
import { Loader2, Pencil, Plus, Sparkles, X } from 'lucide-react'
import { toast } from 'sonner'
import { useResolveTypeSuggestion, useTypeSuggestions, useUpdateTypeSuggestion } from '@/lib/queries'
import { canExecute } from '@/lib/auth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { SuggestedFieldType, TypeSuggestion } from '@/types/api'

const FIELD_TYPES: SuggestedFieldType[] = ['str', 'int', 'float', 'bool', 'list']

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
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Campo</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead>Descripción</TableHead>
                <TableHead>Requerido</TableHead>
                {isEditing && <TableHead className="w-8" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {(isEditing ? fields : suggestion.fields).map((field, index) =>
                isEditing ? (
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
                        <SelectTrigger className="h-8 w-24 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {FIELD_TYPES.map((t) => (
                            <SelectItem key={t} value={t}>
                              {t}
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
                ) : (
                  <TableRow key={field.name}>
                    <TableCell className="font-mono text-xs">{field.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{field.field_type}</TableCell>
                    <TableCell className="text-xs">{field.description}</TableCell>
                    <TableCell>{field.required ? 'Sí' : 'No'}</TableCell>
                  </TableRow>
                ),
              )}
            </TableBody>
          </Table>
        </div>

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
        <h1 className="text-2xl font-semibold tracking-tight">Sugerencias de tipo</h1>
        <p className="text-muted-foreground">
          Cuando un documento cae en <code>generic</code>, el sistema puede proponer un tipo nuevo. Antes de decidir, se
          puede editar la propuesta (nombre, campos). Aceptar solo marca la propuesta como accionable — no registra el
          tipo automáticamente: registrarlo es publicar su definición en el catálogo de tipos.
        </p>
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : !suggestions || suggestions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No hay sugerencias pendientes.</p>
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
