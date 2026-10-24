import { HubCards } from '@/components/layout/HubCards'
import { REPORTS } from '@/components/layout/navigation'

export function ReportsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reportes</h1>
        <p className="text-muted-foreground">Cómo están saliendo las validaciones y cuánto se puede confiar en la lectura automática.</p>
      </div>
      <HubCards pages={REPORTS} />
    </div>
  )
}
