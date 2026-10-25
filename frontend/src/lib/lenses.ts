// The words of the Risk and Legal page (VRT-91): who each area is and how
// much a point of Legal's review weighs.
import type { LensDefinition, PlaybookItem } from '@/types/api'

export const AREA: Record<LensDefinition['area'], { name: string; hint: string }> = {
  riesgos: { name: 'Riesgos', hint: 'Recibe un resumen del expediente con lo que necesita para decidir, cada dato con la cita del documento.' },
  legal: { name: 'Legal', hint: 'Revisa cada documento contra lo que debe cumplir: punto por punto, con la cita que lo prueba.' },
}

export const IMPORTANCE: Record<PlaybookItem['importance'], { label: string; dot: string; chip: string }> = {
  alta: { label: 'Importante', dot: 'bg-red-500', chip: 'bg-red-500/10 text-red-700 dark:text-red-400' },
  media: { label: 'Normal', dot: 'bg-amber-500', chip: 'bg-amber-500/10 text-amber-700 dark:text-amber-400' },
  baja: { label: 'Menor', dot: 'bg-muted-foreground/40', chip: 'bg-muted text-muted-foreground' },
}
