import type { EvalRate } from '@/types/api'

/** "92% (23/25)", or "—" when nothing was evaluated. */
export function percent(rate: EvalRate | null | undefined): string {
  if (!rate || rate.accuracy === null) return '—'
  return `${Math.round(rate.accuracy * 100)}% (${rate.correct}/${rate.evaluated})`
}

export function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
