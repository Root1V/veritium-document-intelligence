// A new test in three questions (VRT-92): which version, against which cases,
// how many. The version comes chosen when the test is asked for from the
// process (its draft), and otherwise defaults to the latest draft.
import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Choice } from '@/components/profiles/RequirementRow'
import { errorDetail } from '@/lib/apiErrors'
import { useProcessProfiles, useStartSimulation } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ProcessProfileSummary } from '@/types/api'

const VERSION_STATUS: Record<string, string> = { draft: 'borrador', published: 'publicada', retired: 'retirada' }
const LIMITS = [20, 50, 100, 200]

/** The version a test is usually about: the newest draft, else the newest one. */
function defaultVersion(p: ProcessProfileSummary | undefined): string {
  const newest = [...(p?.versions ?? [])].sort((a, b) => b.version - a.version)
  return String((newest.find((v) => v.status === 'draft') ?? newest[0])?.version ?? '')
}

export function NewTestDialog({ initial, onStarted, onClose }: { initial: { profile?: string; version?: string }; onStarted: (id: string) => void; onClose: () => void }) {
  const { data: profiles } = useProcessProfiles()
  const start = useStartSimulation()
  const [profileKey, setProfileKey] = useState(initial.profile ?? '')
  const [picked, setVersion] = useState(initial.version ?? '')
  const [kind, setKind] = useState<'what_if' | 'shadow'>('what_if')
  const [limit, setLimit] = useState(50)
  const profile = profiles?.find((p) => p.key === profileKey)
  const version = picked || defaultVersion(profile)

  function submit() {
    start.mutate(
      { profile_key: profileKey, profile_version: Number(version), kind, case_limit: limit },
      {
        onSuccess: (s) => {
          toast.success(kind === 'shadow' ? 'Sombra encendida: se aplicará a los próximos expedientes.' : 'Prueba en curso.')
          onStarted(s.id)
        },
        onError: (e) => toast.error(errorDetail(e)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>Nueva prueba</DialogTitle>
          <DialogDescription>Mira qué decisiones cambiarían con una versión del proceso, sin tocar ningún expediente ni avisar a nadie.</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 py-5">
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">1. ¿Qué versión pruebas?</h3>
            <div className="flex flex-wrap gap-2">
              <Choice
                value={profileKey}
                placeholder="Proceso"
                className="w-64"
                options={(profiles ?? []).map((p) => ({ value: p.key, label: p.name }))}
                onChange={(k) => {
                  setProfileKey(k)
                  setVersion('')
                }}
              />
              {profile && (
                <Choice
                  value={version}
                  className="w-64"
                  options={[...profile.versions]
                    .sort((a, b) => b.version - a.version)
                    .map((v) => ({
                      value: String(v.version),
                      label: `Versión ${v.version} · ${VERSION_STATUS[v.status] ?? v.status}${v.version === profile.active_version ? ' (en uso)' : ''}`,
                    }))}
                  onChange={setVersion}
                />
              )}
            </div>
            {profile && Number(version) === profile.active_version && (
              <p className="text-xs text-amber-700 dark:text-amber-400">Es la versión en uso: la prueba dará lo mismo que hoy. Normalmente se prueba el borrador.</p>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">2. ¿Con qué expedientes?</h3>
            <div className="grid gap-2 sm:grid-cols-2">
              {(
                [
                  ['what_if', 'Con expedientes pasados', 'Recalcula la decisión de los últimos expedientes con lo que ya se leyó de sus documentos. Tarda poco.'],
                  ['shadow', 'En sombra con los nuevos', 'Cada expediente nuevo se decide también con esta versión, sin afectar la decisión real, hasta que la detengas.'],
                ] as const
              ).map(([value, title, text]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setKind(value)}
                  className={cn('flex flex-col gap-1 rounded-lg border px-3 py-2.5 text-left text-sm transition', kind === value ? 'border-primary bg-primary/5' : 'hover:bg-muted/50')}
                >
                  <span className="font-medium">{title}</span>
                  <span className="text-xs text-muted-foreground">{text}</span>
                </button>
              ))}
            </div>
          </section>

          {kind === 'what_if' && (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold">3. ¿Cuántos?</h3>
              <div className="flex flex-wrap gap-1.5">
                {LIMITS.map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setLimit(n)}
                    className={cn('rounded-md border px-3 py-1.5 text-sm transition', limit === n ? 'border-primary bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:text-foreground')}
                  >
                    Los últimos {n}
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>

        <DialogFooter className="border-t px-6 py-4">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={submit} disabled={!profileKey || !version || start.isPending}>
            {start.isPending && <Loader2 className="size-4 animate-spin" />} {kind === 'shadow' ? 'Encender la sombra' : 'Probar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
