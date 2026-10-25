// Getting started (VRT-71, VRT-86): what a business unit needs to process
// cases, in order and in business words. Each step checks itself against the
// platform (people, document types, catalog, rules, processes, cases), says
// who does it and leads to where it is done; the next one comes first.
import { useState, type ReactNode } from 'react'
import { isAxiosError } from 'axios'
import { Link } from 'react-router-dom'
import { ArrowRight, Building2, Check, ChevronDown, Loader2, Repeat, ShieldCheck, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { getUnit, getUnits, isAdmin, isPlatformAdmin } from '@/lib/auth'
import {
  useApiClients,
  useCases,
  useDocumentTypeCatalog,
  useProcessProfiles,
  useReviewQueue,
  useSemanticCatalog,
  useToggleRules,
  useUsers,
  useValidationRules,
} from '@/lib/queries'
import { cn } from '@/lib/utils'

type Who = 'unidad' | 'plataforma' | 'operador'
type State = 'done' | 'pending' | 'unknown' | 'loading'

const WHO: Record<Who, { label: string; icon: typeof Users; ask: string; does: string }> = {
  unidad: { label: 'Admin de la unidad', icon: Building2, ask: 'Pídeselo al admin de tu unidad.', does: 'Su equipo, su proceso y los sistemas que envían expedientes.' },
  plataforma: {
    label: 'Equipo de plataforma',
    icon: ShieldCheck,
    ask: 'Si falta algo, pídeselo al equipo de plataforma.',
    does: 'Lo que comparten todas las unidades: documentos, significado de los datos y reglas.',
  },
  operador: { label: 'Operadores', icon: Users, ask: '', does: 'Prueban con expedientes reales y revisan lo que la plataforma no leyó bien.' },
}

interface Step {
  key: string
  title: string
  who: Who
  body: string
  state: State
  fact: string
  /** The main action while the step is pending, and the way to see it once done. */
  action: { to: string; label: string; seen: string }
  more?: { to: string; label: string }
  /** Not part of getting ready: optional, or the day-to-day work after it. */
  kind?: 'optional' | 'ongoing'
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** A query's answer as a step's state and the fact it shows. */
function check<T>(q: { data?: T; isLoading: boolean; error: unknown }, read: (data: T) => [boolean, string]): [State, string] {
  if (q.isLoading) return ['loading', 'Comprobando…']
  if (isAxiosError(q.error) && q.error.response?.status === 404) return ['pending', 'Aún no está hecho']
  if (q.error || q.data === undefined) return ['unknown', 'No tienes acceso para comprobarlo.']
  const [done, fact] = read(q.data)
  return [done ? 'done' : 'pending', fact]
}

function useSteps(): Step[] {
  const users = useUsers()
  const types = useDocumentTypeCatalog()
  const catalog = useSemanticCatalog()
  const rules = useValidationRules({ status_filter: 'active' })
  const builtIn = useToggleRules()
  const profiles = useProcessProfiles()
  const cases = useCases()
  const queue = useReviewQueue()
  const clients = useApiClients()

  const team = check(users, (u) => {
    const operators = u.filter((p) => p.role === 'operador').length
    return [operators > 0, `${plural(u.length, 'persona', 'personas')} · ${plural(operators, 'operador', 'operadores')}`]
  })
  const documents = check(types, (t) => [t.registered.length > 0, plural(t.registered.length, 'tipo de documento', 'tipos de documento')])
  const meaning = check(catalog, (c) => [c.status === 'published', `Versión ${c.version} · ${plural(c.catalog.attributes.length, 'dato definido', 'datos definidos')}`])
  // The built-in rules (toggles) plus the ones written here; a toggle's override is not another rule.
  const validation = check(builtIn, (t) => {
    const n = t.filter((x) => x.status === 'active').length + (rules.data ?? []).filter((r) => r.kind !== 'toggle').length
    return [n > 0, plural(n, 'regla activa', 'reglas activas')]
  })
  const process = check(profiles, (p) => {
    const live = p.filter((x) => x.key !== 'ad-hoc' && x.active_version !== null)
    return [live.length > 0, live.length ? `${live.map((x) => x.name).join(', ')} · publicado` : 'Aún no hay procesos publicados']
  })
  const tried = check(cases, (c) => [c.length > 0, c.length ? plural(c.length, 'expediente procesado', 'expedientes procesados') : 'Aún no hay expedientes'])
  const review = check(queue, (q) => [q.length === 0, q.length ? `${plural(q.length, 'campo espera', 'campos esperan')} revisión` : 'Al día: nada por revisar'])
  const systems = check(clients, (c) => {
    const active = c.filter((x) => !x.revoked_at).length
    return [active > 0, active ? plural(active, 'sistema conectado', 'sistemas conectados') : 'Ninguno conectado']
  })

  return [
    {
      key: 'team', title: 'Tu equipo', who: 'unidad', state: team[0], fact: team[1],
      body: 'Quién trabaja en la unidad y con qué rol. Las personas entran con su cuenta corporativa y su rol viene de sus grupos. Hace falta al menos un operador que suba y revise expedientes.',
      action: { to: '/users', label: 'Agregar personas', seen: 'Ver personas' },
    },
    {
      key: 'documents', title: 'Los documentos que recibes', who: 'plataforma', state: documents[0], fact: documents[1],
      body: 'Los tipos de documento que la plataforma reconoce (boleta, documento de identidad, solicitud…). Si a tu proceso le falta alguno, se crea a partir de un documento de ejemplo y sirve para todas las unidades.',
      action: { to: '/document-types', label: 'Crear un tipo de documento', seen: 'Ver tipos de documento' },
    },
    {
      key: 'meaning', title: 'Qué significa cada dato', who: 'plataforma', state: meaning[0], fact: meaning[1],
      body: 'Cada dato de un documento se conecta a su significado de negocio —el DNI del titular, su ingreso neto— y se marca si es personal o sensible. Así se comparan los documentos entre sí y se protege lo sensible.',
      action: { to: '/semantic-catalog', label: 'Publicar el catálogo', seen: 'Ver catálogo de datos' },
    },
    {
      key: 'validation', title: 'Qué se comprueba', who: 'plataforma', state: validation[0], fact: validation[1],
      body: 'Las reglas que revisan los datos: que coincidan entre documentos, que tengan el formato correcto, que los montos cuadren. Cada proceso elige cuáles aplica y qué tan graves son.',
      action: { to: '/validation-rules', label: 'Crear reglas', seen: 'Ver reglas' },
    },
    {
      key: 'process', title: 'Tu proceso', who: 'unidad', state: process[0], fact: process[1],
      body: 'Qué documentos exige, qué comprueba, desde qué confianza un dato pasa a revisión humana y cuántos días se guardan los datos personales después de decidir.',
      action: { to: '/profiles', label: 'Crear tu proceso', seen: 'Ver procesos' },
    },
    {
      key: 'try', title: 'Pruébalo con un expediente', who: 'operador', state: tried[0], fact: tried[1],
      body: 'Sube documentos reales y mira qué decide la plataforma y por qué. Antes de publicar una versión nueva del proceso, compara cómo habría decidido los expedientes anteriores.',
      action: { to: '/upload', label: 'Crear un expediente de prueba', seen: 'Nuevo expediente' },
      more: { to: '/simulations', label: 'Probar cambios' },
    },
    {
      key: 'systems', title: 'Conecta tus sistemas', who: 'unidad', state: systems[0], fact: systems[1], kind: 'optional',
      body: 'Si otro sistema del banco enviará los expedientes, créale sus credenciales: llamará a la plataforma por su cuenta y con su propio límite de llamadas.',
      action: { to: '/sistemas', label: 'Conectar un sistema', seen: 'Ver sistemas conectados' },
    },
    {
      key: 'review', title: 'Revisa y ajusta', who: 'operador', state: review[0], fact: review[1], kind: 'ongoing',
      body: 'Corrige lo que la plataforma no leyó bien. Cada corrección queda registrada con su motivo y sirve para medir y mejorar la lectura.',
      action: { to: '/review', label: 'Ir a revisar', seen: 'Ir a revisar' },
    },
  ]
}

const mine = (who: Who) => (who === 'plataforma' ? isPlatformAdmin() : who === 'unidad' ? isAdmin() : true)

function Marker({ step, number, next }: { step: Step; number: number; next: boolean }) {
  const base = 'relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold'
  if (step.state === 'loading') return <span className={cn(base, 'border bg-background')}><Loader2 className="size-4 animate-spin text-muted-foreground" /></span>
  if (step.kind === 'ongoing') return <span className={cn(base, 'bg-sky-500/10 text-sky-600 dark:text-sky-400')}><Repeat className="size-4" /></span>
  if (step.state === 'done') return <span className={cn(base, 'bg-emerald-500 text-white')}><Check className="size-4" /></span>
  if (next) return <span className={cn(base, 'bg-primary text-primary-foreground ring-4 ring-primary/15')}>{number}</span>
  return <span className={cn(base, 'border-2 bg-background text-muted-foreground', step.kind === 'optional' && 'border-dashed')}>{number}</span>
}

function Tag({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium', className)}>{children}</span>
}

/** Who does what, with how many of their steps are ready. */
function Roles({ roles, className }: { roles: { who: Who; ready: number; total: number }[]; className?: string }) {
  return (
    <Card className={className}>
      <CardContent className="flex flex-col gap-4 p-5">
        <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Quién hace qué</span>
        {roles.map(({ who, ready: ok, total }) => {
          const Icon = WHO[who].icon
          return (
            <div key={who} className="flex gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <Icon className="size-4" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">
                    {WHO[who].label}
                    {mine(who) && who !== 'operador' && <span className="ml-1.5 text-xs font-normal text-primary">tú</span>}
                  </span>
                  {total > 0 && (
                    <span className={cn('text-xs tabular-nums', ok === total ? 'text-emerald-700 dark:text-emerald-400' : 'text-muted-foreground')}>
                      {ok}/{total}
                    </span>
                  )}
                </div>
                <span className="text-xs text-muted-foreground">{WHO[who].does}</span>
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

export function GettingStartedPage() {
  const unit = getUnits().find((u) => u.key === getUnit())?.name ?? 'tu unidad'
  const steps = useSteps()
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const required = steps.filter((s) => !s.kind)
  const done = required.filter((s) => s.state === 'done').length
  const loading = required.some((s) => s.state === 'loading')
  const next = required.find((s) => s.state === 'pending' || s.state === 'unknown')
  const ready = !loading && !next

  const pct = Math.round((done / required.length) * 100)
  const roles = (Object.keys(WHO) as Who[]).map((who) => {
    const own = required.filter((s) => s.who === who)
    return { who, ready: own.filter((s) => s.state === 'done').length, total: own.length }
  })
  const reviewStep = steps.find((s) => s.kind === 'ongoing')

  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Primeros pasos</h1>
        <p className="text-muted-foreground">Lo necesario para que {unit} procese expedientes, en orden. Cada paso se marca solo cuando está listo.</p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-start">
        {/* Beside the steps on wide screens, above them on narrow ones. */}
        <aside className="flex flex-col gap-4 xl:sticky xl:top-20 xl:order-2">
          <Card>
            <CardContent className="flex flex-col gap-3 p-5">
              <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Avance</span>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-semibold tabular-nums">{loading ? '…' : `${pct}%`}</span>
                <span className="text-sm text-muted-foreground">
                  {done} de {required.length} pasos
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div className={cn('h-full rounded-full transition-all', ready ? 'bg-emerald-500' : 'bg-primary')} style={{ width: `${pct}%` }} />
              </div>
              {loading ? (
                <p className="text-sm text-muted-foreground">Comprobando cada paso…</p>
              ) : next ? (
                <>
                  <div className="flex flex-col gap-0.5 rounded-lg bg-muted/60 px-3 py-2">
                    <span className="text-xs text-muted-foreground">Siguiente paso</span>
                    <span className="text-sm font-medium">{next.title}</span>
                    <span className="text-xs text-muted-foreground">Lo hace: {WHO[next.who].label.toLowerCase()}</span>
                  </div>
                  {mine(next.who) ? (
                    <Button asChild>
                      <Link to={next.action.to}>
                        {next.action.label} <ArrowRight className="size-4" />
                      </Link>
                    </Button>
                  ) : (
                    <p className="text-xs text-muted-foreground">{WHO[next.who].ask}</p>
                  )}
                </>
              ) : (
                <>
                  <p className="flex items-start gap-2 text-sm">
                    <Check className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    <span>
                      <span className="font-medium">{unit} está lista.</span> <span className="text-muted-foreground">Lo que sigue es el día a día: revisar y ajustar.</span>
                    </span>
                  </p>
                  {reviewStep && (
                    <Button asChild variant="outline">
                      <Link to={reviewStep.action.to}>
                        Ir a revisar <ArrowRight className="size-4" />
                      </Link>
                    </Button>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          <Roles roles={roles} className="hidden xl:flex" />
        </aside>

        <ol className="relative flex flex-col">
          {steps.map((step, i) => {
            const isNext = step === next
            const open = toggled[step.key] ?? isNext
            const yours = mine(step.who)
            const Who = WHO[step.who].icon
            const last = i === steps.length - 1
            return (
              <li key={step.key} className="relative flex gap-4 pb-3">
                {!last && <span className="absolute top-8 bottom-0 left-4 w-px -translate-x-1/2 bg-border" aria-hidden />}
                <Marker step={step} number={i + 1} next={isNext} />
                <div className={cn('flex min-w-0 flex-1 flex-col rounded-xl border bg-card transition-colors', isNext && 'border-primary/40 shadow-sm')}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-3 px-4 py-3 text-left"
                    onClick={() => setToggled({ ...toggled, [step.key]: !open })}
                    aria-expanded={open}
                  >
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{step.title}</span>
                        {step.kind === 'optional' && <Tag className="bg-muted text-muted-foreground">Opcional</Tag>}
                        {step.kind === 'ongoing' && <Tag className="bg-muted text-muted-foreground">Día a día</Tag>}
                        {isNext && <Tag className="bg-primary/10 text-primary">Siguiente paso</Tag>}
                      </div>
                      <span
                        className={cn(
                          'text-sm',
                          step.state === 'done' && !step.kind ? 'text-emerald-700 dark:text-emerald-400' : 'text-muted-foreground',
                          step.kind === 'ongoing' && step.state === 'pending' && 'text-amber-700 dark:text-amber-400',
                        )}
                      >
                        {step.fact}
                      </span>
                    </div>
                    <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
                      <Who className="size-3.5" /> {WHO[step.who].label}
                    </span>
                    <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
                  </button>

                  {open && (
                    <div className="flex flex-col gap-3 border-t px-4 py-3">
                      <p className="max-w-3xl text-sm text-muted-foreground">{step.body}</p>
                      <span className="flex items-center gap-1.5 text-xs text-muted-foreground sm:hidden">
                        <Who className="size-3.5" /> Lo hace: {WHO[step.who].label}
                      </span>
                      <div className="flex flex-wrap items-center gap-2">
                        {step.state !== 'done' && yours ? (
                          <Button asChild size="sm">
                            <Link to={step.action.to}>
                              {step.action.label} <ArrowRight className="size-3.5" />
                            </Link>
                          </Button>
                        ) : (
                          <Button asChild size="sm" variant="outline">
                            <Link to={step.action.to}>{step.action.seen}</Link>
                          </Button>
                        )}
                        {step.more && (
                          <Button asChild size="sm" variant="ghost">
                            <Link to={step.more.to}>{step.more.label}</Link>
                          </Button>
                        )}
                        {step.state !== 'done' && !yours && <span className="text-xs text-muted-foreground">{WHO[step.who].ask}</span>}
                      </div>
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>

        <Roles roles={roles} className="xl:hidden" />
      </div>
    </div>
  )
}
