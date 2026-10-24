// Getting started (VRT-71): the order in which a business unit gets ready to
// process cases, in business words, with who does each step and a link to it.
import { Link } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { getUnit, getUnits, isAdmin, isPlatformAdmin } from '@/lib/auth'

type Who = 'unidad' | 'plataforma' | 'operador'

const WHO_LABEL: Record<Who, string> = {
  unidad: 'Lo hace el admin de tu unidad',
  plataforma: 'Lo hace el equipo de plataforma',
  operador: 'Lo hace cualquier operador',
}

const STEPS: { title: string; who: Who; body: string; links: { to: string; label: string }[] }[] = [
  {
    title: 'Tu equipo',
    who: 'unidad',
    body: 'Quién trabaja en la unidad y con qué rol. Las personas entran con su cuenta corporativa: su unidad y su rol vienen de sus grupos. Aquí ves quiénes están.',
    links: [{ to: '/users', label: 'Usuarios' }],
  },
  {
    title: 'Los documentos que recibes',
    who: 'plataforma',
    body: 'Revisa si los tipos de documento de tu proceso ya existen (boleta, documento de identidad, solicitud…). Si falta alguno, el equipo de plataforma lo crea a partir de un documento de ejemplo; sirve para todas las unidades.',
    links: [{ to: '/document-types', label: 'Tipos de documento' }],
  },
  {
    title: 'Qué significa cada dato',
    who: 'plataforma',
    body: 'Cada campo de un documento se conecta a un atributo con significado de negocio — el DNI del titular, su ingreso neto — y se marca si es un dato personal o sensible. Así se comparan los documentos entre sí y se protege lo sensible.',
    links: [{ to: '/semantic-catalog', label: 'Catálogo de datos' }],
  },
  {
    title: 'Qué se valida',
    who: 'plataforma',
    body: 'Las reglas que comprueban los datos: que coincidan entre documentos, que tengan el formato correcto, que los montos cuadren. Tu proceso elige cuáles aplica y con qué severidad.',
    links: [{ to: '/validation-rules', label: 'Reglas de validación' }],
  },
  {
    title: 'Tu proceso',
    who: 'unidad',
    body: 'Crea el perfil de tu proceso: qué documentos o evidencias exige, qué reglas aplica, desde qué confianza un dato pasa a revisión humana y cuántos días se conservan los datos personales después de decidir.',
    links: [{ to: '/profiles', label: 'Procesos' }],
  },
  {
    title: 'Pruébalo',
    who: 'operador',
    body: 'Crea un expediente de prueba con documentos reales y mira qué decide la plataforma y por qué. Antes de publicar una versión nueva del proceso, compara cómo habría decidido los expedientes anteriores.',
    links: [
      { to: '/upload', label: 'Nuevo expediente' },
      { to: '/simulations', label: 'Probar cambios' },
    ],
  },
  {
    title: 'Revisa y ajusta',
    who: 'operador',
    body: 'Corrige lo que la plataforma no leyó bien. Cada corrección queda auditada, con su motivo, y sirve para medir y mejorar la lectura.',
    links: [{ to: '/review', label: 'Revisar' }],
  },
  {
    title: 'Conecta tus sistemas (opcional)',
    who: 'unidad',
    body: 'Si otro sistema del banco enviará los expedientes, créale sus credenciales: llamará a la plataforma por su cuenta y con su propio límite de llamadas.',
    links: [{ to: '/sistemas', label: 'Sistemas conectados' }],
  },
]

export function GettingStartedPage() {
  const unit = getUnits().find((u) => u.key === getUnit())?.name
  const mine = (who: Who) => (who === 'plataforma' ? isPlatformAdmin() : who === 'unidad' ? isAdmin() : true)

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Primeros pasos</h1>
        <p className="text-muted-foreground">
          Cómo dejar lista {unit ?? 'tu unidad'} para procesar expedientes, en este orden. Lo que comparten todas las unidades — documentos,
          significado de los datos y reglas — lo prepara el equipo de plataforma; tu proceso y tu equipo, el admin de tu unidad.
        </p>
      </div>
      <ol className="flex flex-col gap-3">
        {STEPS.map((step, i) => (
          <li key={step.title}>
            <Card className={mine(step.who) ? '' : 'opacity-75'}>
              <CardContent className="flex gap-4 p-4">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                  {i + 1}
                </span>
                <div className="flex flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{step.title}</span>
                    <Badge variant={mine(step.who) ? 'secondary' : 'outline'} className="text-[10px]">
                      {WHO_LABEL[step.who]}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">{step.body}</p>
                  <div className="flex flex-wrap gap-3 text-sm">
                    {step.links.map((l) => (
                      <Link key={l.to} to={l.to} className="text-primary underline-offset-2 hover:underline">
                        {l.label} →
                      </Link>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </li>
        ))}
      </ol>
    </div>
  )
}
