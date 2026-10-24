// A status in words, with a color and an icon so it never rests on color alone (VRT-73).
import { CircleAlert, CircleCheck, CircleDashed, CircleX, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { documentStatus, type Tone } from '@/lib/labels'

const STYLE: Record<Tone, { className: string; Icon: typeof CircleCheck }> = {
  ok: { className: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950/40 dark:text-emerald-300', Icon: CircleCheck },
  warn: { className: 'bg-amber-50 text-amber-800 ring-amber-600/20 dark:bg-amber-950/40 dark:text-amber-300', Icon: CircleAlert },
  bad: { className: 'bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-950/40 dark:text-red-300', Icon: CircleX },
  busy: { className: 'bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-950/40 dark:text-sky-300', Icon: Loader2 },
  neutral: { className: 'bg-muted text-muted-foreground ring-border', Icon: CircleDashed },
}

export function ToneBadge({ tone, label, className }: { tone: Tone; label: string; className?: string }) {
  const { className: style, Icon } = STYLE[tone]
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap', style, className)}>
      <Icon className={cn('size-3', tone === 'busy' && 'animate-spin')} aria-hidden />
      {label}
    </span>
  )
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const { label, tone } = documentStatus(status)
  return <ToneBadge tone={tone} label={label} className={className} />
}
