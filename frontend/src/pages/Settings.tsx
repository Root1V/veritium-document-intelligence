import { HubCards } from '@/components/layout/HubCards'
import { GETTING_STARTED, SETTINGS } from '@/components/layout/navigation'
import { isAdmin } from '@/lib/auth'

export function SettingsPage() {
  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Configuración</h1>
        <p className="text-muted-foreground">Cómo trabaja Veritium en esta unidad: sus procesos, los documentos que reconoce, sus reglas y quién tiene acceso.</p>
      </div>
      {isAdmin() && <HubCards pages={[GETTING_STARTED]} />}
      {SETTINGS.map((group) => {
        const visible = group.pages.filter((p) => !p.show || p.show())
        if (visible.length === 0) return null
        return (
          <section key={group.label} className="flex flex-col gap-3">
            <h2 className="text-sm font-medium text-muted-foreground">{group.label}</h2>
            <HubCards pages={visible} />
          </section>
        )
      })}
    </div>
  )
}
