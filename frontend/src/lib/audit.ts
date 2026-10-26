// The words of the audit page (VRT-102): what each access to personal data
// was, and the records grouped by the day they happened.
import { Clock, Download, Eye, Search, ShieldOff, Trash2, type LucideIcon } from 'lucide-react'
import type { DataAccessEntry } from '@/types/api'

export const ACTION: Record<string, { icon: LucideIcon; tone: string }> = {
  ver_datos: { icon: Eye, tone: 'bg-sky-500/10 text-sky-700 dark:text-sky-300' },
  descargar_original: { icon: Download, tone: 'bg-sky-500/10 text-sky-700 dark:text-sky-300' },
  buscar: { icon: Search, tone: 'bg-sky-500/10 text-sky-700 dark:text-sky-300' },
  suprimir: { icon: ShieldOff, tone: 'bg-amber-500/10 text-amber-700 dark:text-amber-300' },
  vencer: { icon: Clock, tone: 'bg-muted text-muted-foreground' },
  eliminar: { icon: Trash2, tone: 'bg-red-500/10 text-red-700 dark:text-red-300' },
}

export const CHANNEL: Record<string, string> = { web: 'desde la pantalla', api: 'desde un sistema conectado' }

/** A process of the platform itself — tests, retention — and not a person. */
export const automatic = (e: DataAccessEntry) => e.role === 'sistema'

export const time = (iso: string) => new Date(iso).toLocaleTimeString('es-PE', { hour: 'numeric', minute: '2-digit' })

function dayOf(iso: string, now = new Date()): string {
  const d = new Date(iso)
  const days = Math.round((new Date(now.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 86_400_000)
  if (days === 0) return 'Hoy'
  if (days === 1) return 'Ayer'
  return d.toLocaleDateString('es-PE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

/** Newest first, as they come: consecutive records of the same day together. */
export function byDay<T>(items: T[], at: (item: T) => string): { day: string; items: T[] }[] {
  const out: { day: string; items: T[] }[] = []
  for (const item of items) {
    const day = dayOf(at(item))
    if (out.at(-1)?.day === day) out.at(-1)!.items.push(item)
    else out.push({ day, items: [item] })
  }
  return out
}
