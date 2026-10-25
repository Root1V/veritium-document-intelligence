import { useState } from 'react'
import { Loader2, Pencil, Plus, Sparkles, Wand2 } from 'lucide-react'
import { isAxiosError } from 'axios'
import { toast } from 'sonner'
import {
  useCreateManualRule,
  useDocumentTypeCatalog,
  useDraftValidationRule,
  useResolveValidationRule,
  useRunRuleTests,
  useSemanticCatalog,
  useSetRuleToggle,
  useToggleRules,
  useUpdateValidationRule,
  useValidationRules,
} from '@/lib/queries'
import { isPlatformAdmin } from '@/lib/auth'
import { DeleteButton } from '@/components/DeleteButton'
import { ToneBadge } from '@/components/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { RuleCelCategory, RuleTestCase, RuleTestResult, ValidationRule } from '@/types/api'
import { SharedConfigNote } from '@/components/layout/SharedConfigNote'

const CATEGORY_OPTIONS: { value: RuleCelCategory; label: string }[] = [
  { value: 'self', label: 'Interna del documento' },
  { value: 'request_input', label: 'Datos de entrada' },
  { value: 'reference_data', label: 'Existe en datos de referencia' },
]
const CATEGORY_LABEL: Record<string, string> = {
  ...Object.fromEntries(CATEGORY_OPTIONS.map((c) => [c.value, c.label])),
  cross_document: 'Entre documentos',
  external_system: 'Sistema externo',
  conditional: 'Condicional',
  semantic: 'Entre documentos',
}
const SEVERITY_OPTIONS = ['info', 'warning', 'error'] as const

function errorDetail(error: unknown, fallback: string): string {
  const detail = isAxiosError(error) ? error.response?.data?.detail : undefined
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => (typeof d === 'string' ? d : d.msg)).join(' · ')
  return fallback
}

// Only what the case sets: empty `doc`/`case`/`request` are noise.
function compactInput(input: RuleTestCase['input']): string {
  const set = Object.entries(input).filter(([, v]) => v !== null && v !== undefined && !(typeof v === 'object' && Object.keys(v as object).length === 0))
  return JSON.stringify(Object.fromEntries(set))
}

function NewRuleForm() {
  const { data: catalog } = useDocumentTypeCatalog()
  const { data: semantic } = useSemanticCatalog()
  const draftMutation = useDraftValidationRule()
  const manualMutation = useCreateManualRule()
  const [manualMode, setManualMode] = useState(false)

  const [target, setTarget] = useState<'document' | 'attribute'>('attribute')
  const [documentType, setDocumentType] = useState('')
  const [attribute, setAttribute] = useState('')
  const [questions, setQuestions] = useState<string[]>([])
  const [category, setCategory] = useState<RuleCelCategory>('self')
  const [fieldPath, setFieldPath] = useState('')
  const [description, setDescription] = useState('')
  const [ruleIdSuffix, setRuleIdSuffix] = useState('')
  const [conditionCel, setConditionCel] = useState('')
  const [severity, setSeverity] = useState<'info' | 'warning' | 'error'>('warning')
  const [messagePass, setMessagePass] = useState('')
  const [messageFail, setMessageFail] = useState('')

  const isPending = draftMutation.isPending || manualMutation.isPending

  function resetForm() {
    setFieldPath('')
    setDescription('')
    setRuleIdSuffix('')
    setConditionCel('')
    setMessagePass('')
    setMessageFail('')
  }

  const scope = target === 'attribute' ? { attribute } : { document_type: documentType }

  function handleSubmit() {
    if (target === 'document' ? !documentType : !attribute) {
      toast.error(target === 'document' ? 'Elige un tipo de documento.' : 'Elige un atributo.')
      return
    }
    if (manualMode) {
      if (!ruleIdSuffix.trim() || !conditionCel.trim() || !messagePass.trim() || !messageFail.trim()) {
        toast.error('Completa el identificador, la condición CEL y ambos mensajes.')
        return
      }
      manualMutation.mutate(
        {
          rule_id_suffix: ruleIdSuffix.trim(),
          ...scope,
          category,
          field_path: fieldPath || undefined,
          condition_cel: conditionCel,
          severity,
          message_pass: messagePass,
          message_fail: messageFail,
        },
        {
          onSuccess: () => {
            toast.success('Regla creada como borrador.')
            resetForm()
          },
          onError: (error) => toast.error(errorDetail(error, 'No se pudo crear la regla.')),
        },
      )
    } else {
      if (!description.trim()) {
        toast.error('Describe la regla en lenguaje natural.')
        return
      }
      const existingFieldsHint = target === 'document' ? catalog?.registered.find((t) => t.name === documentType)?.fields.map((f) => f.name) : undefined
      draftMutation.mutate(
        { description, ...scope, category, field_path: fieldPath || undefined, existing_fields_hint: existingFieldsHint },
        {
          onSuccess: (data) => {
            if (data.outcome === 'ambiguous') {
              setQuestions(data.questions)
              toast.info('La descripción es ambigua: responde las preguntas en la descripción y vuelve a generar.')
              return
            }
            setQuestions([])
            toast.success('Borrador generado con IA — revísalo abajo antes de activarlo.')
            resetForm()
          },
          onError: (error) => toast.error(errorDetail(error, 'No se pudo generar el borrador.')),
        },
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Nueva regla</CardTitle>
        <CardDescription>
          Sobre un atributo del catálogo semántico (corre en cualquier documento que lo aporte) o sobre los campos de
          un tipo de documento. Puede comparar con el expediente (<code>case</code>) y con los datos del proceso
          (<code>request</code>). Cada regla trae casos de prueba, y solo se activa si todos dan lo esperado.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-3">
          <div className="flex flex-col gap-1">
            <Label>La regla es sobre</Label>
            <Select value={target} onValueChange={(v) => setTarget(v as typeof target)}>
              <SelectTrigger className="w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="attribute">Un atributo (cualquier documento)</SelectItem>
                <SelectItem value="document">Un tipo de documento</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {target === 'attribute' ? (
            <div className="flex flex-col gap-1">
              <Label>Atributo</Label>
              <Select value={attribute} onValueChange={setAttribute}>
                <SelectTrigger className="w-64">
                  <SelectValue placeholder="Elegir atributo" />
                </SelectTrigger>
                <SelectContent>
                  {semantic?.catalog.attributes.map((a) => (
                    <SelectItem key={a.key} value={a.key}>
                      {a.key}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : (
          <div className="flex flex-col gap-1">
            <Label>Tipo de documento</Label>
            <Select value={documentType} onValueChange={setDocumentType}>
              <SelectTrigger className="w-56">
                <SelectValue placeholder="Elegir tipo" />
              </SelectTrigger>
              <SelectContent>
                {catalog?.registered.map((type) => (
                  <SelectItem key={type.name} value={type.name}>
                    {type.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          )}
          <div className="flex flex-col gap-1">
            <Label>Categoría</Label>
            <Select value={category} onValueChange={(v) => setCategory(v as RuleCelCategory)}>
              <SelectTrigger className="w-64">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CATEGORY_OPTIONS.map((c) => (
                  <SelectItem key={c.value} value={c.value}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label>Campo (opcional)</Label>
            <Input value={fieldPath} onChange={(e) => setFieldPath(e.target.value)} placeholder="p. ej. net_pay" className="w-44" />
          </div>
        </div>

        {!manualMode ? (
          <div className="flex flex-col gap-2">
            <Label>Descripción en lenguaje natural</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={
                target === 'attribute'
                  ? 'p. ej. el ingreso neto mensual debe ser de al menos 1025 soles (remuneración mínima vital)'
                  : 'p. ej. el neto de la boleta debe ser igual al bruto menos los descuentos, con una tolerancia de 0.01'
              }
              rows={3}
            />
            {questions.length > 0 && (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
                <p className="font-medium">AMBIGUA — la IA no inventa lo que falta. Precisa en la descripción:</p>
                <ul className="mt-1 list-disc pl-5">
                  {questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <Label>Identificador de la regla</Label>
              <Input value={ruleIdSuffix} onChange={(e) => setRuleIdSuffix(e.target.value)} placeholder="p. ej. net_pay_tolerance" />
            </div>
            <div className="flex flex-col gap-1">
              <Label>Condición CEL</Label>
              <Textarea
                value={conditionCel}
                onChange={(e) => setConditionCel(e.target.value)}
                placeholder="has(doc.net_pay) && doc.net_pay > 0.0"
                className="font-mono text-xs"
                rows={2}
              />
            </div>
            <div className="flex flex-wrap gap-3">
              <div className="flex flex-col gap-1">
                <Label>Severidad</Label>
                <Select value={severity} onValueChange={(v) => setSeverity(v as typeof severity)}>
                  <SelectTrigger className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SEVERITY_OPTIONS.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-1 flex-col gap-1">
                <Label>Mensaje si cumple</Label>
                <Input value={messagePass} onChange={(e) => setMessagePass(e.target.value)} />
              </div>
              <div className="flex flex-1 flex-col gap-1">
                <Label>Mensaje si no cumple</Label>
                <Input value={messageFail} onChange={(e) => setMessageFail(e.target.value)} />
              </div>
            </div>
          </div>
        )}

        <div className="flex items-center gap-2">
          <Button size="sm" disabled={isPending} onClick={handleSubmit}>
            {isPending ? <Loader2 className="size-3.5 animate-spin" /> : manualMode ? <Pencil className="size-3.5" /> : <Wand2 className="size-3.5" />}
            {manualMode ? 'Crear borrador' : 'Generar con IA'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setManualMode((v) => !v)}>
            {manualMode ? 'Volver a lenguaje natural' : 'Escribir CEL manualmente'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function RuleDraftCard({ rule }: { rule: ValidationRule }) {
  const update = useUpdateValidationRule()
  const resolve = useResolveValidationRule()
  const runTests = useRunRuleTests()
  const [results, setResults] = useState<RuleTestResult[] | undefined>()
  const [testCasesJson, setTestCasesJson] = useState(JSON.stringify(rule.test_cases, null, 2))
  const [isEditing, setIsEditing] = useState(false)
  const [conditionCel, setConditionCel] = useState(rule.condition_cel ?? '')
  const [appliesWhenCel, setAppliesWhenCel] = useState(rule.applies_when_cel ?? '')
  const [severity, setSeverity] = useState(rule.severity ?? 'warning')
  const [messagePass, setMessagePass] = useState(rule.message_pass ?? '')
  const [messageFail, setMessageFail] = useState(rule.message_fail ?? '')

  const canSave = conditionCel.trim().length > 0 && messagePass.trim().length > 0 && messageFail.trim().length > 0

  function startEditing() {
    setConditionCel(rule.condition_cel ?? '')
    setAppliesWhenCel(rule.applies_when_cel ?? '')
    setSeverity(rule.severity ?? 'warning')
    setMessagePass(rule.message_pass ?? '')
    setMessageFail(rule.message_fail ?? '')
    setTestCasesJson(JSON.stringify(rule.test_cases, null, 2))
    setIsEditing(true)
  }

  function handleRunTests() {
    runTests.mutate(rule.id, {
      onSuccess: (data) => setResults(data.results),
      onError: (error) => toast.error(errorDetail(error, 'No se pudieron correr los casos.')),
    })
  }

  function handleSave() {
    let testCases: RuleTestCase[]
    try {
      testCases = JSON.parse(testCasesJson)
    } catch {
      toast.error('Los casos de prueba no son JSON válido.')
      return
    }
    setResults(undefined)
    update.mutate(
      {
        id: rule.id,
        body: { condition_cel: conditionCel, applies_when_cel: appliesWhenCel || undefined, severity, message_pass: messagePass, message_fail: messageFail, test_cases: testCases },
      },
      {
        onSuccess: () => {
          toast.success('Borrador actualizado.')
          setIsEditing(false)
        },
        onError: (error) => toast.error(errorDetail(error, 'No se pudo guardar — revisa la condición CEL.')),
      },
    )
  }

  function handleResolve(decision: 'activate' | 'reject') {
    resolve.mutate(
      { id: rule.id, decision },
      {
        onSuccess: () => toast.success(decision === 'activate' ? 'Regla activada.' : 'Regla rechazada.'),
        onError: (error) => toast.error(errorDetail(error, 'No se pudo procesar la decisión.')),
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          <CardTitle className="text-base">{rule.rule_id}</CardTitle>
          <Badge variant="outline" className="text-[10px]">
            {CATEGORY_LABEL[rule.category] ?? rule.category}
          </Badge>
          {rule.document_type && (
            <Badge variant="outline" className="text-[10px]">
              {rule.document_type}
            </Badge>
          )}
          {rule.attribute && (
            <Badge variant="secondary" className="text-[10px]">
              atributo {rule.attribute}
            </Badge>
          )}
        </div>
        {rule.description_nl && <CardDescription>{rule.description_nl}</CardDescription>}
        {rule.rationale && <p className="text-xs text-muted-foreground">{rule.rationale}</p>}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {isEditing ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <Label>Condición CEL</Label>
              <Textarea value={conditionCel} onChange={(e) => setConditionCel(e.target.value)} className="font-mono text-xs" rows={2} />
            </div>
            <div className="flex flex-col gap-1">
              <Label>Condición adicional (opcional)</Label>
              <Textarea value={appliesWhenCel} onChange={(e) => setAppliesWhenCel(e.target.value)} className="font-mono text-xs" rows={2} />
            </div>
            <div className="flex flex-wrap gap-3">
              <div className="flex flex-col gap-1">
                <Label>Severidad</Label>
                <Select value={severity} onValueChange={(v) => setSeverity(v as typeof severity)}>
                  <SelectTrigger className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SEVERITY_OPTIONS.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-1 flex-col gap-1">
                <Label>Mensaje si cumple</Label>
                <Input value={messagePass} onChange={(e) => setMessagePass(e.target.value)} />
              </div>
              <div className="flex flex-1 flex-col gap-1">
                <Label>Mensaje si no cumple</Label>
                <Input value={messageFail} onChange={(e) => setMessageFail(e.target.value)} />
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <Label>Casos de prueba (JSON: name, input &#123;value | doc | case | request&#125;, expect pass|fail)</Label>
              <Textarea value={testCasesJson} onChange={(e) => setTestCasesJson(e.target.value)} className="font-mono text-xs" rows={6} />
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            <code className="rounded-md bg-muted px-2 py-1.5 text-xs">{rule.condition_cel}</code>
            {rule.applies_when_cel && <code className="rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground">aplica si: {rule.applies_when_cel}</code>}
            <div className="mt-1 flex items-center gap-2 text-xs">
              <Badge variant="outline" className="text-[10px]">
                {rule.severity}
              </Badge>
              <span className="text-muted-foreground">{rule.message_fail}</span>
            </div>
            <div className="mt-2 flex flex-col gap-1">
              <span className="text-xs font-medium">Casos de prueba ({rule.test_cases.length})</span>
              {rule.test_cases.length === 0 && <span className="text-xs text-muted-foreground">Sin casos: no se puede activar hasta tener uno que cumpla y uno que no.</span>}
              {rule.test_cases.map((c, i) => {
                const result = results?.[i]
                return (
                  <div key={i} className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant="outline" className="text-[10px]">
                      espera {c.expect}
                    </Badge>
                    {result && (
                      <Badge variant={result.got === c.expect ? 'secondary' : 'destructive'} className="text-[10px]">
                        dio {result.got}
                      </Badge>
                    )}
                    <span>{c.name}</span>
                    <code className="text-muted-foreground">{compactInput(c.input)}</code>
                  </div>
                )
              })}
            </div>
          </div>
        )}

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
              <Button size="sm" variant="outline" disabled={runTests.isPending} onClick={handleRunTests}>
                {runTests.isPending && <Loader2 className="size-3.5 animate-spin" />}
                Probar casos
              </Button>
              <Button size="sm" disabled={resolve.isPending} onClick={() => handleResolve('activate')}>
                Activar
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
                path={`/validation-rules/${rule.id}`}
                question="Se eliminará para siempre este borrador de regla. Nunca se aplicó a ningún expediente."
              />
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

const SEVERITY_LABEL: Record<string, string> = { info: 'Informativa', warning: 'Advertencia', error: 'Error' }

/** Every rule in force — the platform's and the ones written here — said by what it checks (VRT-79). */
function RulesTable() {
  const { data: custom } = useValidationRules({ kind: 'cel', status_filter: 'active' })
  const { data: toggles, isLoading } = useToggleRules()
  const resolve = useResolveValidationRule()
  const setToggle = useSetRuleToggle()
  const canChange = isPlatformAdmin()

  if (isLoading) {
    return (
      <div className="flex h-24 items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }
  const rows = [
    ...(custom ?? []).map((r) => ({
      key: r.id,
      what: r.description_nl || r.message_fail || r.rule_id,
      code: r.rule_id,
      origin: 'Creada aquí',
      category: r.category,
      severity: r.severity,
      active: true,
      technical: r.condition_cel,
      toggle: () => resolve.mutate({ id: r.id, decision: 'disable' }, { onSuccess: () => toast.success('Regla desactivada.') }),
      pending: resolve.isPending && resolve.variables?.id === r.id,
    })),
    ...(toggles ?? []).map((t) => ({
      key: t.rule_id,
      what: t.description || t.rule_id,
      code: t.rule_id,
      origin: 'Del sistema',
      category: t.category,
      severity: null,
      active: t.status === 'active',
      technical: null,
      toggle: () =>
        setToggle.mutate({ ruleId: t.rule_id, action: t.status === 'active' ? 'disable' : 'enable' }, { onSuccess: () => toast.success('Actualizado.') }),
      pending: setToggle.isPending && setToggle.variables?.ruleId === t.rule_id,
    })),
  ]

  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Qué verifica</TableHead>
            <TableHead>Tipo</TableHead>
            <TableHead>Origen</TableHead>
            <TableHead>Estado</TableHead>
            {canChange && <TableHead className="w-28" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.key}>
              <TableCell className="max-w-xl whitespace-normal">
                <span className="text-sm">{r.what}</span>
                <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground" title={r.technical ?? undefined}>
                  {r.code}
                </span>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {CATEGORY_LABEL[r.category] ?? r.category}
                {r.severity && <span className="block text-xs">{SEVERITY_LABEL[r.severity] ?? r.severity}</span>}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">{r.origin}</TableCell>
              <TableCell>
                <ToneBadge tone={r.active ? 'ok' : 'neutral'} label={r.active ? 'Activa' : 'Desactivada'} />
              </TableCell>
              {canChange && (
                <TableCell>
                  <Button size="sm" variant="outline" disabled={r.pending} onClick={r.toggle}>
                    {r.active ? 'Desactivar' : 'Activar'}
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function ValidationRulesPage() {
  const canResolve = isPlatformAdmin() // the rule library runs in every unit (VRT-71)
  const { data: drafts, isLoading } = useValidationRules({ kind: 'cel', status_filter: 'draft' })
  const [creating, setCreating] = useState(false)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Reglas de validación</h1>
          <p className="text-muted-foreground">Las comprobaciones que se hacen a cada documento y expediente. Una regla nueva se describe en palabras y se prueba antes de activarla.</p>
        </div>
        {canResolve && (
          <Button variant={creating ? 'outline' : 'default'} onClick={() => setCreating((c) => !c)}>
            {creating ? 'Cerrar' : <><Plus className="size-4" /> Nueva regla</>}
          </Button>
        )}
      </div>
      <SharedConfigNote show={!isPlatformAdmin()} />

      {canResolve && creating && <NewRuleForm />}

      {isLoading ? (
        <div className="flex h-24 items-center justify-center">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        </div>
      ) : drafts && drafts.length > 0 ? (
        <section className="flex flex-col gap-4">
          <h2 className="text-lg font-semibold tracking-tight">Borradores por revisar ({drafts.length})</h2>
          {drafts.map((rule) => (
            <RuleDraftCard key={rule.id} rule={rule} />
          ))}
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold tracking-tight">Reglas</h2>
        <RulesTable />
      </section>
    </div>
  )
}
