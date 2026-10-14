import { type FormEvent, useEffect, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Building2, FileStack, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

  return (
    <div className="flex min-h-svh items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <FileStack className="size-6" />
          </div>
          <CardTitle>Plataforma Documental</CardTitle>
          <CardDescription>{finishing ? 'Completando tu ingreso…' : 'Ingresa para continuar'}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {finishing ? (
            <Loader2 className="mx-auto size-6 animate-spin text-muted-foreground" />
          ) : (
            <>
              {providers.data?.sso && (
                <Button asChild variant={local ? 'outline' : 'default'}>
                  <a href={ssoHref}>
                    <Building2 className="size-4" />
                    Ingresar con tu cuenta corporativa
                  </a>
                </Button>
              )}
              {providers.data?.sso && local && (
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="h-px flex-1 bg-border" />o con correo y contraseña<span className="h-px flex-1 bg-border" />
                </div>
              )}
              {local && (
                <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="email">Correo</Label>
                    <Input
                      id="email"
                      type="email"
                      autoComplete="username"
                      required
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
                  <Button type="submit" disabled={login.isPending} className="mt-2">
                    {login.isPending && <Loader2 className="size-4 animate-spin" />}
                    Ingresar
                  </Button>
                </form>
              )}
              {error && <p className="text-sm text-destructive">{error}</p>}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
