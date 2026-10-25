// A rule waiting to be switched on (VRT-36, VRT-90): what it checks, how
// Veritium understood it and its test cases in words; "Probar y activar"
// runs the cases and switches it on only if every one gives what it should.
// The condition and the cases themselves are folded, for whoever adjusts them.
import { useState } from 'react'
import { CheckCircle2, Circle, Loader2, Sparkles, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Choice } from '@/components/profiles/RequirementRow'
import { errorDetail } from '@/lib/apiErrors'
import { useResolveValidationRule, useRunRuleTests, useUpdateValidationRule } from '@/lib/queries'
import { SEVERITY, groupOf } from '@/lib/validationRules'
import type { RuleTestCase, RuleTestResult, ValidationRule } from '@/types/api'

const OUTCOME = { pass: 'cumple', fail: 'no cumple', error: 'da error' } as const

// Only what the case sets: empty `doc`/`case`/`request` are noise.
function compactInput(input: RuleTestCase['input']): string {
  const set = Object.entries(input).filter(([, v]) => v !== null && v !== undefined && !(typeof v === 'object' && Object.keys(v as object).length === 0))
  return JSON.stringify(Object.fromEntries(set))
}

export function DraftRuleCard({ rule, about }: { rule: ValidationRule; about: string | null }) {
  const update = useUpdateValidationRule()
  const resolve = useResolveValidationRule()
  const runTests = useRunRuleTests()
  const [results, setResults] = useState<RuleTestResult[] | undefined>()
  const [edit, setEdit] = useState({
    cel: rule.condition_cel ?? '',
    when: rule.applies_when_cel ?? '',
    severity: rule.severity ?? 'warning',
    pass: rule.message_pass ?? '',
    fail: rule.message_fail ?? '',
    cases: JSON.stringify(rule.test_cases, null, 2),
  })
  const busy = runTests.isPending || resolve.isPending
  const severity = SEVERITY[rule.severity ?? 'warning']

  function tryAndActivate() {
    runTests.mutate(rule.id, {
      onSuccess: (data) => {
        setResults(data.results)
        if (!data.all_ok) {
          const wrong = data.results.filter((r) => r.got !== r.expect).length
          return void toast.error(
            data.results.length && wrong ? `${wrong} de ${data.results.length} casos no dieron lo esperado: ajústala antes de activarla.` : 'Necesita un caso que cumpla y uno que no.',
          )
        }
        resolve.mutate(
          { id: rule.id, decision: 'activate' },
          { onSuccess: () => toast.success('Regla activada: corre desde el próximo expediente.'), onError: (e) => toast.error(errorDetail(e)) },
        )
      },
      onError: (e) => toast.error(errorDetail(e)),
    })
  }

  function save() {
    let cases: RuleTestCase[]
    try {
      cases = JSON.parse(edit.cases)
    } catch {
      return void toast.error('Los casos de prueba no son JSON válido.')
    }
    setResults(undefined)
    update.mutate(
      {
        id: rule.id,
        body: { condition_cel: edit.cel, applies_when_cel: edit.when || undefined, severity: edit.severity, message_pass: edit.pass, message_fail: edit.fail, test_cases: cases },
      },
      { onSuccess: () => toast.success('Ajustes guardados.'), onError: (e) => toast.error(errorDetail(e)) },
    )
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border bg-card p-5">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400">
          <Sparkles className="size-4" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="font-medium first-letter:uppercase">{rule.description_nl || rule.message_fail || rule.rule_id}</p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {about && <span>Sobre: {about}</span>}
            <span>{groupOf(rule.category).name}</span>
            <span className="inline-flex items-center gap-1.5">
              <span className={`size-2 rounded-full ${severity.dot}`} /> Si falla: {severity.label.toLowerCase()}
            </span>
          </div>
        </div>
      </div>

      {(rule.rationale || rule.message_fail) && (
        <div className="flex flex-col gap-1 rounded-lg bg-muted/50 px-3 py-2 text-sm">
          {rule.rationale && (
            <p>
              <span className="text-muted-foreground">Cómo la entendió Veritium: </span>
              {rule.rationale}
            </p>
          )}
          {rule.message_fail && (
            <p>
              <span className="text-muted-foreground">Si no se cumple, el expediente dirá: </span>«{rule.message_fail}»
            </p>
          )}
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-muted-foreground">Casos de prueba ({rule.test_cases.length})</span>
        {rule.test_cases.length === 0 && <span className="text-sm text-muted-foreground">Sin casos: necesita uno que cumpla y uno que no.</span>}
        <ul className="flex flex-col gap-1 text-sm">
          {rule.test_cases.map((c, i) => {
            const got = results?.[i]?.got
            const ok = got === c.expect
            return (
              <li key={i} className="flex flex-wrap items-center gap-x-2" title={compactInput(c.input)}>
                {got === undefined ? (
                  <Circle className="size-4 shrink-0 text-muted-foreground/50" />
                ) : ok ? (
                  <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />
                ) : (
                  <XCircle className="size-4 shrink-0 text-red-600" />
                )}
                <span>{c.name}</span>
                <span className="text-xs text-muted-foreground">
                  · debe {OUTCOME[c.expect]}
                  {got !== undefined && !ok && <span className="text-red-600"> pero {OUTCOME[got]}</span>}
                </span>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={busy} onClick={tryAndActivate}>
          {busy && <Loader2 className="size-3.5 animate-spin" />} Probar y activar
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() =>
            resolve.mutate({ id: rule.id, decision: 'reject' }, { onSuccess: () => toast.success('Regla descartada.'), onError: (e) => toast.error(errorDetail(e)) })
          }
        >
          Descartar
        </Button>
      </div>

      <details className="text-xs text-muted-foreground">
        <summary className="w-fit cursor-pointer select-none hover:text-foreground">Ajustar la condición y los casos</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            Condición (CEL) · <code className="text-[11px]">{rule.rule_id}</code>
            <Textarea value={edit.cel} onChange={(e) => setEdit({ ...edit, cel: e.target.value })} className="font-mono text-xs" rows={2} />
          </label>
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            Solo aplica si (opcional)
            <Textarea value={edit.when} onChange={(e) => setEdit({ ...edit, when: e.target.value })} className="font-mono text-xs" rows={1} />
          </label>
          <label className="flex flex-col gap-1.5">
            Gravedad si falla
            <Choice value={edit.severity} className="h-8" options={Object.entries(SEVERITY).map(([value, s]) => ({ value, label: s.label }))} onChange={(v) => setEdit({ ...edit, severity: v as typeof edit.severity })} />
          </label>
          <span />
          <label className="flex flex-col gap-1.5">
            Mensaje si cumple
            <Input value={edit.pass} onChange={(e) => setEdit({ ...edit, pass: e.target.value })} className="h-8 text-xs" />
          </label>
          <label className="flex flex-col gap-1.5">
            Mensaje si no cumple
            <Input value={edit.fail} onChange={(e) => setEdit({ ...edit, fail: e.target.value })} className="h-8 text-xs" />
          </label>
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            Casos de prueba (JSON: name, input &#123;value | doc | case | request&#125;, expect pass|fail)
            <Textarea value={edit.cases} onChange={(e) => setEdit({ ...edit, cases: e.target.value })} className="font-mono text-xs" rows={6} />
          </label>
          <Button size="sm" variant="outline" className="self-start" disabled={update.isPending || !edit.cel.trim()} onClick={save}>
            {update.isPending && <Loader2 className="size-3.5 animate-spin" />} Guardar ajustes
          </Button>
        </div>
      </details>
    </div>
  )
}
