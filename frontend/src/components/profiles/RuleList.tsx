// What a process checks (VRT-37, VRT-87): each bound rule with what happens
// when it fails, said as an outcome — not as severity plus a "blocking" flag —
// and a searchable picker that puts first the rules for the documents asked.
import { useState } from 'react'
import { Check, Plus, Search, Sparkles, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Choice } from '@/components/profiles/RequirementRow'
import { OUTCOME, outcomeOf, type Outcome } from '@/lib/processProfile'
import { cn } from '@/lib/utils'
import type { ProfileLibrary, RuleBinding } from '@/types/api'

type Rule = ProfileLibrary['rules'][number]
const KIND: Record<Rule['kind'], string> = { format: 'Formato', cel: 'Regla de negocio', code: 'Del sistema' }

export function RuleList({ bindings, library, suggested, onChange }: {
  bindings: RuleBinding[]
  library: ProfileLibrary
  /** Rules not bound yet that run on the documents this process asks for, or other processes use. */
  suggested: { rule: Rule; runsOn: string[] }[]
  onChange: (bindings: RuleBinding[]) => void
}) {
  const [picking, setPicking] = useState(false)
  const [query, setQuery] = useState('')
  const describe = (id: string) => library.rules.find((r) => r.rule_id === id)
  const typeName = (key: string) => library.document_types.find((t) => t.key === key)?.display_name ?? key
  const bound = new Set(bindings.map((b) => b.rule_id))
  const add = (rule_id: string) => onChange([...bindings, { rule_id, ...OUTCOME.warn.binding }])
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const matches = (r: Rule) => words.every((w) => `${r.description} ${r.applies_to.map(typeName).join(' ')}`.toLowerCase().includes(w))
  const suggestedIds = new Set(suggested.map((s) => s.rule.rule_id))
  const others = library.rules.filter((r) => !suggestedIds.has(r.rule_id))

  function option(rule: Rule, why?: string) {
    const added = bound.has(rule.rule_id)
    return (
      <li key={rule.rule_id} className="flex items-start gap-3 rounded-md px-2 py-2 hover:bg-muted/50">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-sm">{rule.description || rule.rule_id}</span>
          <span className="text-xs text-muted-foreground">
            {KIND[rule.kind]}
            {why && ` · ${why}`}
          </span>
        </div>
        <Button size="sm" variant={added ? 'ghost' : 'outline'} className="h-7 shrink-0" disabled={added} onClick={() => add(rule.rule_id)}>
          {added ? <Check className="size-3.5" /> : <Plus className="size-3.5" />} {added ? 'Agregada' : 'Agregar'}
        </Button>
      </li>
    )
  }
  const why = (s: { rule: Rule; runsOn: string[] }) =>
    [s.runsOn.length ? `revisa ${s.runsOn.map(typeName).join(', ')}` : '', s.rule.used_by.length ? `la usa ${s.rule.used_by.join(', ')}` : ''].filter(Boolean).join(' · ')

  return (
    <div className="flex flex-col gap-2">
      {bindings.length === 0 && <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">Aún no comprueba nada. Agrega las comprobaciones que necesita.</p>}
      {bindings.map((b, i) => {
        const rule = describe(b.rule_id)
        const outcome = outcomeOf(b)
        return (
          <div key={b.rule_id} className="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-3">
            <div className="flex min-w-60 flex-1 flex-col gap-0.5">
              <span className="text-sm">{rule?.description || b.rule_id}</span>
              <span className="text-xs text-muted-foreground">{rule ? KIND[rule.kind] : 'No está en el catálogo de esta versión'}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Si falla</span>
              <Choice
                value={outcome}
                className={cn('w-56', OUTCOME[outcome].tone)}
                options={(Object.keys(OUTCOME) as Outcome[]).map((o) => ({ value: o, label: OUTCOME[o].label }))}
                onChange={(v) => onChange(bindings.map((x, j) => (j === i ? { rule_id: x.rule_id, ...OUTCOME[v as Outcome].binding } : x)))}
              />
              <Button variant="ghost" size="icon" className="size-9 text-muted-foreground" onClick={() => onChange(bindings.filter((_, j) => j !== i))} aria-label="Quitar comprobación">
                <Trash2 className="size-4" />
              </Button>
            </div>
          </div>
        )
      })}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => setPicking(true)}>
          <Plus className="size-3.5" /> Agregar comprobación
        </Button>
        {suggested.slice(0, 3).map((s) => (
          <button
            key={s.rule.rule_id}
            type="button"
            onClick={() => add(s.rule.rule_id)}
            title={why(s)}
            className="inline-flex max-w-72 items-center gap-1 truncate rounded-full border border-dashed px-2.5 py-1 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
          >
            <Sparkles className="size-3 shrink-0 text-primary" /> <span className="truncate">{s.rule.description || s.rule.rule_id}</span>
          </button>
        ))}
      </div>

      <Dialog open={picking} onOpenChange={setPicking}>
        <DialogContent className="flex max-h-[85svh] flex-col gap-3 sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Agregar comprobaciones</DialogTitle>
            <DialogDescription>Primero las que revisan los documentos que pide este proceso. Puedes agregar varias.</DialogDescription>
          </DialogHeader>
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Busca por lo que comprueba o por documento…" className="pl-8" />
          </div>
          <div className="-mx-2 min-h-0 flex-1 overflow-y-auto">
            {suggested.filter((s) => matches(s.rule)).length > 0 && (
              <>
                <p className="px-2 pt-1 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Sugeridas para este proceso</p>
                <ul>
                  {suggested.filter((s) => matches(s.rule)).map((s) => (
                    option(s.rule, why(s))
                  ))}
                </ul>
              </>
            )}
            <p className="px-2 pt-3 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Todas</p>
            <ul>
              {others.filter(matches).map((r) => (
                option(r, r.applies_to.length ? `revisa ${r.applies_to.map(typeName).join(', ')}` : undefined)
              ))}
            </ul>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
