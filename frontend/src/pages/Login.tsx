import { type FormEvent, useEffect, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Building2, CheckCircle2, FileStack, Loader2 } from 'lucide-react'
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
    <div className="grid min-h-svh lg:grid-cols-2">
      <aside className="hidden flex-col justify-between bg-sidebar p-10 text-sidebar-foreground lg:flex">
        <div className="flex items-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
            <FileStack className="size-5" />
          </div>
          <span className="text-lg font-semibold text-white">Veritium</span>
        </div>
        <div className="flex max-w-md flex-col gap-6">
          <h2 className="text-3xl font-semibold leading-tight text-white">Decide sobre cada expediente con la evidencia a la vista.</h2>
          <ul className="flex flex-col gap-3 text-sm">
            {[
              'Lee y valida los documentos que llegan, sin teclear.',
              'Te dice qué falta y qué revisar, lo más urgente primero.',
              'Cada dato con el lugar del documento de donde salió.',
            ].map((line) => (
              <li key={line} className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-sidebar-primary" />
                {line}
              </li>
            ))}
          </ul>
        </div>
        <span className="text-xs text-sidebar-foreground/50">Los datos personales se muestran solo a quien los necesita y queda registro.</span>
      </aside>

      <main className="flex items-center justify-center px-6 py-12">
        <div className="flex w-full max-w-sm flex-col gap-6">
          <div className="flex flex-col gap-1">
            <div className="mb-4 flex items-center gap-2 lg:hidden">
              <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <FileStack className="size-5" />
              </div>
              <span className="text-lg font-semibold">Veritium</span>
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">{finishing ? 'Completando tu ingreso…' : 'Ingresa a Veritium'}</h1>
            {!finishing && <p className="text-sm text-muted-foreground">{sso ? 'Usa la misma cuenta con la que entras a tu correo de trabajo.' : 'Usa tu correo y contraseña.'}</p>}
          </div>

          {finishing ? (
            <Loader2 className="mx-auto size-6 animate-spin text-muted-foreground" />
          ) : (
            <div className="flex flex-col gap-4">
              {error && (
                <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {error}
                </p>
              )}
              {sso && (
                <Button asChild size="lg">
                  <a href={ssoHref}>
                    <Building2 className="size-4" />
                    Ingresar con tu cuenta corporativa
                  </a>
                </Button>
              )}
              {sso && local && !showLocal && (
                <button type="button" onClick={() => setShowLocal(true)} className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                  No tengo cuenta corporativa: usar correo y contraseña
                </button>
              )}
              {showForm && (
                <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="email">Correo</Label>
                    <Input
                      id="email"
                      type="email"
                      autoComplete="username"
                      placeholder="nombre@empresa.com"
                      required
                      autoFocus
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="password">Contraseña</Label>
                    <Input
                      id="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </div>
                  <Button type="submit" size="lg" variant={sso ? 'outline' : 'default'} disabled={login.isPending}>
                    {login.isPending && <Loader2 className="size-4 animate-spin" />}
                    Ingresar
                  </Button>
                </form>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
