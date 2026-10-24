import { type FormEvent, useEffect, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, Building2, CheckCircle2, CircleAlert, Eye, EyeOff, FileSearch, FileStack, Loader2, Lock, Mail, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { fetchMe, useLogin, useSignInProviders } from '@/lib/queries'
import { clearSession, getLastUnit, isAuthenticated, setIdToken, setSession, setToken } from '@/lib/auth'

// Why the corporate sign-in did not go through (?sso=… from /auth/oidc/callback).
const SSO_ERROR: Record<string, string> = {
  sin_unidades: 'Tu cuenta no tiene ninguna unidad de negocio asignada. Pídela a tu administrador.',
  rechazado: 'No se pudo validar tu ingreso. Vuelve a intentarlo.',
  cancelado: 'Se canceló el ingreso.',
  proveedor: 'El servicio de ingreso corporativo no responde. Inténtalo en unos minutos.',
}

export function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const login = useLogin()
  const providers = useSignInProviders()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(SSO_ERROR[params.get('sso') ?? ''] ?? null)
  const [finishing, setFinishing] = useState(window.location.hash.startsWith('#token='))
  const [showLocal, setShowLocal] = useState(false)
  const [revealed, setRevealed] = useState(false)

  // Back from the corporate sign-in: the token comes in the fragment, which never reaches a server.
  useEffect(() => {
    const hash = window.location.hash
    if (!hash.startsWith('#token=')) return
    window.history.replaceState(null, '', window.location.pathname)
    const fragment = new URLSearchParams(hash.slice(1))
    const token = fragment.get('token') ?? ''
    setToken(token)
    const idToken = fragment.get('id_token')
    if (idToken) setIdToken(idToken)
    fetchMe()
      .then((me) => {
        setSession(token, me)
        navigate('/', { replace: true })
      })
      .catch(() => {
        clearSession()
        setFinishing(false)
        setError(SSO_ERROR.rechazado)
      })
  }, [navigate])

  if (isAuthenticated() && !finishing) {
    return <Navigate to="/" replace />
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    login.mutate(
      { email, password, tenant: getLastUnit() ?? undefined },
      {
        onSuccess: (data) => {
          setSession(data.access_token, data)
          navigate('/', { replace: true })
        },
        onError: (err) => {
          const status = (err as { response?: { status?: number } }).response?.status
          setError(status === 403 ? SSO_ERROR.sin_unidades : 'Correo o contraseña inválidos.')
        },
      },
    )
  }

  const last = getLastUnit()
  const ssoHref = `/api/auth/oidc/login${last ? `?tenant=${encodeURIComponent(last)}` : ''}`
  const local = providers.data?.local ?? true

  // The corporate account first; the password stays for whoever has no such account, folded when both exist (VRT-75).
  const sso = providers.data?.sso ?? false
  const showForm = local && (!sso || showLocal)

  return (
    <div className="grid min-h-svh bg-background lg:grid-cols-[1.1fr_1fr]">
      <Showcase />

      <main className="relative flex flex-col px-6 py-8 sm:px-12">
        <div className="flex items-center gap-2 lg:hidden">
          <Logo />
          <span className="text-lg font-semibold tracking-tight">Veritium</span>
        </div>

        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-8 py-10">
          <div className="flex flex-col gap-2">
            <h1 className="text-3xl font-semibold tracking-tight">{finishing ? 'Completando tu ingreso…' : 'Bienvenido de nuevo'}</h1>
            {!finishing && (
              <p className="text-muted-foreground">{sso ? 'Ingresa con la misma cuenta de tu correo de trabajo.' : 'Ingresa con tu correo y contraseña.'}</p>
            )}
          </div>

          {finishing ? (
            <Loader2 className="mx-auto size-6 animate-spin text-muted-foreground" />
          ) : (
            <div className="flex flex-col gap-5">
              {error && (
                <p role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm text-destructive">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" />
                  {error}
                </p>
              )}
              {sso && (
                <Button asChild size="lg" className="h-11 rounded-lg text-[15px] shadow-sm shadow-primary/30">
                  <a href={ssoHref}>
                    <Building2 className="size-4" />
                    Ingresar con tu cuenta corporativa
                  </a>
                </Button>
              )}
              {sso && local && (
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="h-px flex-1 bg-border" />o<span className="h-px flex-1 bg-border" />
                </div>
              )}
              {sso && local && !showLocal && (
                <Button variant="outline" size="lg" className="h-11 rounded-lg" onClick={() => setShowLocal(true)}>
                  <Mail className="size-4" /> Usar correo y contraseña
                </Button>
              )}
              {showForm && (
                <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="email">Correo</Label>
                    <div className="relative">
                      <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        id="email"
                        type="email"
                        autoComplete="username"
                        placeholder="nombre@empresa.com"
                        required
                        autoFocus
                        className="h-11 rounded-lg pl-9"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="password">Contraseña</Label>
                    <div className="relative">
                      <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        id="password"
                        type={revealed ? 'text' : 'password'}
                        autoComplete="current-password"
                        required
                        className="h-11 rounded-lg px-9"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                      <button
                        type="button"
                        onClick={() => setRevealed((v) => !v)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
                        aria-label={revealed ? 'Ocultar contraseña' : 'Mostrar contraseña'}
                      >
                        {revealed ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                      </button>
                    </div>
                  </div>
                  <Button type="submit" size="lg" className="mt-1 h-11 rounded-lg text-[15px]" variant={sso ? 'secondary' : 'default'} disabled={login.isPending}>
                    {login.isPending ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
                    Ingresar
                  </Button>
                </form>
              )}
            </div>
          )}
        </div>

        <footer className="mx-auto flex w-full max-w-sm items-center justify-between gap-4 text-xs text-muted-foreground">
          <span>¿No puedes ingresar? Pide ayuda a tu administrador.</span>
          <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap">
            <ShieldCheck className="size-3.5" /> Conexión segura
          </span>
        </footer>
      </main>
    </div>
  )
}

function Logo() {
  return (
    <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-blue-700 text-white shadow-lg shadow-blue-900/40">
      <FileStack className="size-5" />
    </div>
  )
}

/** What Veritium does, shown rather than told: a case decided with its evidence. */
function Showcase() {
  return (
    <aside className="relative hidden overflow-hidden bg-sidebar p-12 text-sidebar-foreground lg:flex lg:flex-col">
      <div className="pointer-events-none absolute -left-32 -top-32 size-[28rem] rounded-full bg-blue-600/30 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 right-0 size-[30rem] rounded-full bg-indigo-500/20 blur-3xl" />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage: 'linear-gradient(to right, white 1px, transparent 1px), linear-gradient(to bottom, white 1px, transparent 1px)',
          backgroundSize: '44px 44px',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
        }}
      />

      <div className="relative flex items-center gap-2">
        <Logo />
        <span className="text-lg font-semibold tracking-tight text-white">Veritium</span>
      </div>

      <div className="relative flex flex-1 flex-col justify-center gap-10">
        <div className="flex max-w-lg flex-col gap-4">
          <span className="w-fit rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-sidebar-foreground/80">Plataforma documental</span>
          <h2 className="text-4xl font-semibold leading-[1.15] tracking-tight text-white">
            Decide sobre cada expediente con la <span className="text-blue-400">evidencia a la vista</span>.
          </h2>
          <p className="text-sidebar-foreground/70">Lee los documentos, valida lo que dicen y te dice qué falta o qué revisar. Sin teclear datos.</p>
        </div>

        <div className="relative max-w-md">
          <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-5 pb-12 shadow-2xl shadow-black/40 backdrop-blur">
            <div className="flex items-center justify-between">
              <div className="flex flex-col">
                <span className="text-sm font-semibold text-white">EXP-2026-0142</span>
                <span className="text-xs text-sidebar-foreground/60">Préstamo por convenio · hace 3 min</span>
              </div>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-400/15 px-2.5 py-1 text-xs font-medium text-emerald-300">
                <CheckCircle2 className="size-3.5" /> Puede continuar
              </span>
            </div>
            <ul className="mt-4 flex flex-col gap-2.5 text-sm">
              {[
                'DNI del titular coincide en 3 documentos',
                'El neto de la boleta cuadra con bruto menos descuentos',
                'Están los 4 documentos que pide el proceso',
              ].map((line) => (
                <li key={line} className="flex items-center gap-2 text-sidebar-foreground/85">
                  <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                  {line}
                </li>
              ))}
            </ul>
          </div>
          <div className="absolute -bottom-6 -right-6 flex items-center gap-2.5 rounded-xl border border-white/10 bg-sidebar/90 px-4 py-3 shadow-xl backdrop-blur">
            <span className="flex size-8 items-center justify-center rounded-lg bg-blue-500/20 text-blue-300">
              <FileSearch className="size-4" />
            </span>
            <span className="flex flex-col text-xs">
              <span className="font-medium text-white">Neto a pagar · pág. 1</span>
              <span className="text-sidebar-foreground/60">cada dato con su fuente</span>
            </span>
          </div>
        </div>
      </div>

      <span className="relative text-xs text-sidebar-foreground/50">Los datos personales se muestran solo a quien los necesita, y queda registro.</span>
    </aside>
  )
}
