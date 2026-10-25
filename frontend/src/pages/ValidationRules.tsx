// The checks made to every document and case (VRT-36, VRT-79, VRT-90): each
// rule said by what it checks, grouped by what it compares against, switched
// on and off in place; the ones waiting to be tried come first, and a new one
// is written in words.
import { useState } from 'react'
import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, Plus, Search } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SharedConfigNote } from '@/components/layout/SharedConfigNote'
import { DraftRuleCard } from '@/components/rules/DraftRuleCard'
import { NewRuleDialog } from '@/components/rules/NewRuleDialog'
import { errorDetail } from '@/lib/apiErrors'
import { isPlatformAdmin } from '@/lib/auth'
import { useTypeName } from '@/lib/labels'
import { useProcessProfiles, useProfileLibrary, useResolveValidationRule, useSemanticCatalog, useSetRuleToggle, useToggleRules, useValidationRules } from '@/lib/queries'
import { GROUPS, SEVERITY, groupOf } from '@/lib/validationRules'
import { cn } from '@/lib/utils'
import type { ValidationRule } from '@/types/api'

interface Row {
  key: string
  what: string
  code: string
  technical: string | null
  category: string
  severity: string | null
  origin: string
  about: string | null
  active: boolean
  usedBy: string[]
  toggle: () => void
  pending: boolean
}

function Switch({ on, disabled, onClick, label }: { on: boolean; disabled?: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn('relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition disabled:opacity-50', on ? 'bg-emerald-500' : 'bg-muted-foreground/30')}
    >
      <span className={cn('absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow transition-transform', on && 'translate-x-4')} />
    </button>
  )
}

function RuleRow({ row, canChange }: { row: Row; canChange: boolean }) {
  const [details, setDetails] = useState(false)
  const severity = row.severity ? SEVERITY[row.severity] : null
  return (
    <li className={cn('flex items-start gap-4 px-4 py-3', !row.active && 'bg-muted/30')}>
      {canChange ? (
        <Switch on={row.active} disabled={row.pending} onClick={row.toggle} label={row.active ? 'Desactivar regla' : 'Activar regla'} />
      ) : row.active ? (
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
      ) : (
        <CircleDashed className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className={cn('text-sm first-letter:uppercase', row.active ? 'font-medium' : 'text-muted-foreground')}>{row.what}</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {!row.active && <span className="rounded-full bg-muted px-2 py-0.5 font-medium">Desactivada</span>}
          {row.about && <span>Sobre: {row.about}</span>}
          {severity && (
            <span className="inline-flex items-center gap-1.5">
              <span className={cn('size-2 rounded-full', severity.dot)} /> Si falla: {severity.label.toLowerCase()}
            </span>
          )}
          <span>{row.origin}</span>
          {row.usedBy.length > 0 && <span>La usan: {row.usedBy.join(', ')}</span>}
          <button type="button" className="hover:text-foreground hover:underline" onClick={() => setDetails(!details)}>
            {details ? 'Ocultar detalle técnico' : 'Detalle técnico'}
          </button>
        </div>
        {details && (
          <div className="mt-1 flex flex-col gap-1 rounded-md bg-muted px-2 py-1.5 font-mono text-[11px] text-muted-foreground">
            <span>{row.code}</span>
            {row.technical && <span className="break-all text-foreground">{row.technical}</span>}
          </div>
        )}
      </div>
    </li>
  )
}

export function ValidationRulesPage() {
  const admin = isPlatformAdmin() // the rule library runs in every unit (VRT-71)
  const { data: custom, isLoading: loadingCustom, isError: customFailed, refetch: refetchCustom } = useValidationRules({ kind: 'cel' })
  const { data: toggles, isLoading: loadingToggles, isError: togglesFailed, refetch: refetchToggles } = useToggleRules()
  const { data: semantic } = useSemanticCatalog()
  const { data: library } = useProfileLibrary(undefined)
  const { data: profiles } = useProcessProfiles()
  const typeName = useTypeName()
  const resolve = useResolveValidationRule()
  const setToggle = useSetRuleToggle()
  const [creating, setCreating] = useState(false)
  const [query, setQuery] = useState('')
  const [group, setGroup] = useState<string | null>(null)

  const processName = (key: string) => profiles?.find((p) => p.key === key)?.name ?? key
  const usedBy = (ruleId: string) => (library?.rules.find((r) => r.rule_id === ruleId)?.used_by ?? []).map(processName)
  const aboutOf = (r: ValidationRule) =>
    r.attribute ? (semantic?.catalog.attributes.find((a) => a.key === r.attribute)?.name ?? r.attribute) : r.document_type ? typeName(r.document_type) : null
  const done = (message: string) => ({ onSuccess: () => toast.success(message), onError: (e: unknown) => toast.error(errorDetail(e)) })

  const drafts = (custom ?? []).filter((r) => r.status === 'draft')
  const rows: Row[] = [
    ...(custom ?? [])
      .filter((r) => r.status === 'active' || r.status === 'disabled')
      .map((r) => ({
        key: r.id,
        what: r.description_nl || r.message_fail || r.rule_id,
        code: r.rule_id,
        technical: r.condition_cel,
        category: r.category,
        severity: r.severity,
        origin: r.created_by ? `Creada por ${r.created_by}` : 'Creada aquí',
        about: aboutOf(r),
        active: r.status === 'active',
        usedBy: usedBy(r.rule_id),
        toggle: () =>
          resolve.mutate(
            { id: r.id, decision: r.status === 'active' ? 'disable' : 'enable' },
            done(r.status === 'active' ? 'Regla desactivada.' : 'Regla activada.'),
          ),
        pending: resolve.isPending && resolve.variables?.id === r.id,
      })),
    ...(toggles ?? []).map((t) => ({
      key: t.rule_id,
      what: t.description || t.rule_id,
      code: t.rule_id,
      technical: null,
      category: t.category,
      severity: null,
      origin: 'Del sistema',
      about: null,
      active: t.status === 'active',
      usedBy: usedBy(t.rule_id),
      toggle: () =>
        setToggle.mutate({ ruleId: t.rule_id, action: t.status === 'active' ? 'disable' : 'enable' }, done(t.status === 'active' ? 'Regla desactivada.' : 'Regla activada.')),
      pending: setToggle.isPending && setToggle.variables?.ruleId === t.rule_id,
    })),
  ]
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = rows.filter((r) => words.every((w) => `${r.what} ${r.about ?? ''} ${r.code}`.toLowerCase().includes(w)))
  const active = rows.filter((r) => r.active).length

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Reglas de validación</h1>
          <p className="text-muted-foreground">
            Las comprobaciones que Veritium hace a cada documento y expediente. Cada proceso elige cuáles usa y qué pasa si fallan; una regla nueva se
            escribe en palabras y se prueba antes de activarla.
          </p>
        </div>
        {admin && (
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Nueva regla
          </Button>
        )}
      </div>
      <SharedConfigNote show={!admin} />

      {loadingCustom || loadingToggles ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : customFailed || togglesFailed ? (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm">
          <AlertTriangle className="size-4 text-red-600" />
          <span>No se pudieron cargar las reglas: el servidor de Veritium no responde. No es que no haya reglas.</span>
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            onClick={() => {
              void refetchCustom()
              void refetchToggles()
            }}
          >
            Reintentar
          </Button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-2 text-xs font-medium">
            <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 text-emerald-700 dark:text-emerald-400">{active} activas</span>
            {rows.length > active && <span className="rounded-full bg-muted px-2.5 py-1 text-muted-foreground">{rows.length - active} desactivadas</span>}
            {drafts.length > 0 && (
              <span className="rounded-full bg-amber-500/10 px-2.5 py-1 text-amber-700 dark:text-amber-400">
                {drafts.length === 1 ? '1 por revisar' : `${drafts.length} por revisar`}
              </span>
            )}
          </div>

          {drafts.length > 0 && (
            <section className="flex flex-col gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 sm:p-5">
              <div className="flex items-center gap-2">
                <AlertTriangle className="size-4 text-amber-600 dark:text-amber-400" />
                <h2 className="font-semibold">Por revisar ({drafts.length})</h2>
              </div>
              <p className="-mt-2 text-sm text-muted-foreground">Reglas nuevas que aún no corren. Revisa cómo las entendió Veritium, pruébalas y actívalas.</p>
              {drafts.map((r) => (
                <DraftRuleCard key={r.id} rule={r} about={aboutOf(r)} />
              ))}
            </section>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full max-w-sm">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Busca una regla, p. ej. «código de empleado»" className="pl-8" />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {[{ key: null, name: 'Todas', count: rows.length }, ...GROUPS.map((g) => ({ key: g.key, name: g.name, count: rows.filter((r) => groupOf(r.category).key === g.key).length }))]
                .filter((g) => g.count > 0)
                .map((g) => (
                  <button
                    key={g.key ?? 'all'}
                    type="button"
                    onClick={() => setGroup(g.key)}
                    className={cn('rounded-full border px-3 py-1 text-sm transition', group === g.key ? 'border-primary bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:text-foreground')}
                  >
                    {g.name} <span className="opacity-70">{g.count}</span>
                  </button>
                ))}
            </div>
          </div>

          {GROUPS.filter((g) => !group || g.key === group).map((g) => {
            const list = shown.filter((r) => groupOf(r.category).key === g.key).sort((a, b) => Number(b.active) - Number(a.active))
            if (!list.length) return null
            return (
              <section key={g.key} className="overflow-hidden rounded-2xl border">
                <div className="flex flex-wrap items-baseline gap-x-2 border-b bg-muted/40 px-4 py-3">
                  <h2 className="font-semibold">{g.name}</h2>
                  <span className="text-sm text-muted-foreground">{list.length === 1 ? '1 regla' : `${list.length} reglas`}</span>
                  <p className="w-full text-sm text-muted-foreground">{g.hint}</p>
                </div>
                <ul className="divide-y bg-card">
                  {list.map((r) => (
                    <RuleRow key={r.key} row={r} canChange={admin} />
                  ))}
                </ul>
              </section>
            )
          })}
          {words.length > 0 && !shown.length && <p className="text-sm text-muted-foreground">Ninguna regla coincide con «{query}».</p>}
        </>
      )}

      {creating && <NewRuleDialog onClose={() => setCreating(false)} />}
    </div>
  )
}
