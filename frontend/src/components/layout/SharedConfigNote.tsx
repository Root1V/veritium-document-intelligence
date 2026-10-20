// Shown on what every business unit shares, to whoever cannot change it (VRT-71).
import { Building } from 'lucide-react'

export function SharedConfigNote({ show }: { show: boolean }) {
  if (!show) return null
  return (
    <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground">
      <Building className="size-4" />
      <span>Esto lo comparten todas las unidades: lo cambia el equipo de plataforma. Si necesitas algo nuevo aquí, pídeselo.</span>
    </div>
  )
}
