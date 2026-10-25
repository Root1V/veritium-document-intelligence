// How the process will decide (VRT-87), in words, as it is being edited:
// what returns a case to the client, what sends it to a person, and what
// only leaves a note. Mirrors domain/verdict.py: a missing required document
// returns it, a field read with low confidence or a deciding rule that fails
// sends it to review.
import { CircleCheck, CircleX, TriangleAlert } from 'lucide-react'
import { outcomeOf, whenOf } from '@/lib/processProfile'
import type { ProcessProfileDefinition, ProfileLibrary } from '@/types/api'

function Reasons({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-xs text-muted-foreground">{empty}</p>
  return (
    <ul className="flex flex-col gap-0.5 text-xs text-muted-foreground">
      {items.slice(0, 4).map((t) => (
        <li key={t} className="truncate" title={t}>
          · {t}
        </li>
      ))}
      {items.length > 4 && <li>· y {items.length - 4} más</li>}
    </ul>
  )
}

export function DecisionPreview({ definition, library }: { definition: ProcessProfileDefinition; library: ProfileLibrary }) {
  const describe = (id: string) => library.rules.find((r) => r.rule_id === id)?.description || id
  const by = (o: string) => definition.rule_bindings.filter((b) => outcomeOf(b) === o).map((b) => `Falla: ${describe(b.rule_id)}`)
  const missing = definition.checklist
    .filter((c) => whenOf(c) !== 'optional' && c.label.trim())
    .map((c) => `Falta: ${c.label.trim()}${whenOf(c) === 'condition' ? ' (cuando aplica)' : ''}`)
  const notes = definition.rule_bindings.filter((b) => !b.blocking).length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2.5">
        <CircleX className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" />
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">Devuelve al cliente si…</span>
          <Reasons items={[...missing, ...by('return')]} empty="Nunca: no exige documentos ni tiene comprobaciones que devuelvan." />
        </div>
      </div>
      <div className="flex gap-2.5">
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">Pasa a revisión humana si…</span>
          <Reasons items={['Algún dato se lee con poca confianza', 'Un documento no se pudo leer', ...by('review')]} empty="" />
        </div>
      </div>
      <div className="flex gap-2.5">
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">Continúa en cualquier otro caso</span>
          <p className="text-xs text-muted-foreground">
            {definition.include_all_rules
              ? 'Las demás reglas activas dejan observaciones sin detenerlo.'
              : notes
                ? `${notes} ${notes === 1 ? 'comprobación deja' : 'comprobaciones dejan'} una observación sin detenerlo.`
                : 'Sin observaciones adicionales.'}
          </p>
        </div>
      </div>
    </div>
  )
}
