// Where a case is in its processing (VRT-64): received, reading,
// classification, extraction, validation, decision — each done, running,
// pending or failed. Compact in the list of cases, full in a case.
import { Check, Loader2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { CaseProgress, CaseProgressStep } from '@/types/api'

const BAR = {
  done: 'bg-emerald-500',
  running: 'bg-sky-500 animate-pulse',
  pending: 'bg-muted-foreground/20',
  failed: 'bg-red-500',
} as const

const STATE_WORD = { done: 'hecho', running: 'en curso', pending: 'pendiente', failed: 'con error' } as const

function counts(step: CaseProgressStep): string {
  return step.total ? `${step.done} de ${step.total}` : ''
}

export function ProgressFunnel({ progress, compact = false }: { progress: CaseProgress; compact?: boolean }) {
  if (compact)
    return (
      <div className="flex min-w-48 flex-col gap-1">
        <div className="flex gap-0.5" title={progress.steps.map((s) => `${s.label}: ${STATE_WORD[s.state]}`).join(' · ')}>
          {progress.steps.map((s) => (
            <span key={s.key} className={cn('h-1.5 flex-1 rounded-full', BAR[s.state])} />
          ))}
        </div>
        <span className="text-xs text-muted-foreground">{progress.current}</span>
      </div>
    )

  return (
    <div className="flex flex-col gap-2">
      <ol className="flex items-start">
        {progress.steps.map((s, i) => (
          <li key={s.key} className="flex flex-1 flex-col items-center gap-1 text-center">
            <div className="flex w-full items-center">
              <span className={cn('h-0.5 flex-1', i === 0 ? 'invisible' : progress.steps[i - 1].state === 'done' ? 'bg-emerald-500' : 'bg-muted-foreground/20')} />
              <span
                className={cn(
                  'flex size-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-medium',
                  s.state === 'done' && 'border-emerald-500 bg-emerald-500 text-white',
                  s.state === 'running' && 'border-sky-500 text-sky-600',
                  s.state === 'pending' && 'border-muted-foreground/30 text-muted-foreground',
                  s.state === 'failed' && 'border-red-500 bg-red-500 text-white',
                )}
              >
                {s.state === 'done' ? <Check className="size-4" /> : s.state === 'running' ? <Loader2 className="size-4 animate-spin" /> : s.state === 'failed' ? <X className="size-4" /> : i + 1}
              </span>
              <span className={cn('h-0.5 flex-1', i === progress.steps.length - 1 ? 'invisible' : s.state === 'done' ? 'bg-emerald-500' : 'bg-muted-foreground/20')} />
            </div>
            <span className={cn('text-xs', s.state === 'running' ? 'font-medium text-foreground' : 'text-muted-foreground')}>{s.label}</span>
            {s.key !== 'received' && s.key !== 'decision' && <span className="text-[10px] text-muted-foreground">{counts(s)}</span>}
          </li>
        ))}
      </ol>
      <span className="text-sm text-muted-foreground">{progress.current}</span>
    </div>
  )
}
