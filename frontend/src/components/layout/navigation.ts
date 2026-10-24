// Where everything lives (VRT-73): a few sections by task, each shown only to
// the roles that work in it. The sidebar, the tabs inside a section and the
// index pages (Reportes, Configuración) all read this one list.
import type { LucideIcon } from 'lucide-react'
import {
  BarChart3,
  BookOpen,
  Bot,
  Building2,
  ClipboardCheck,
  Compass,
  FlaskConical,
  FolderOpen,
  Gauge,
  History,
  House,
  KeyRound,
  ListChecks,
  MessageSquareText,
  Network,
  Scale,
  Settings,
  ShieldCheck,
  SplitSquareHorizontal,
  Users,
  Workflow,
  Wrench,
} from 'lucide-react'
import { canEditPrompts, getUserRole, isAdmin, isPlatformAdmin } from '@/lib/auth'

export interface Page {
  to: string
  label: string
  description: string
  icon: LucideIcon
  show?: () => boolean
}

export interface Section {
  to: string
  label: string
  icon: LucideIcon
  /** Paths that belong to it, so it stays highlighted on its pages. */
  match: string[]
  show: () => boolean
  end?: boolean
}

const role = () => getUserRole()
const supervises = () => ['admin', 'visor', 'especialista_ia'].includes(role() ?? '') || isPlatformAdmin()
const configures = () => isAdmin() || role() === 'especialista_ia' || isPlatformAdmin()

export const GROUPS: { label: string | null; sections: Section[] }[] = [
  {
    label: null,
    sections: [
      { to: '/', label: 'Inicio', icon: House, match: [], end: true, show: () => true },
      { to: '/cases', label: 'Expedientes', icon: FolderOpen, match: ['/cases', '/documents', '/bulk', '/batches', '/upload'], show: () => true },
      { to: '/review', label: 'Revisar', icon: ClipboardCheck, match: ['/review', '/type-suggestions'], show: () => true },
      { to: '/asistente', label: 'Asistente', icon: Bot, match: ['/asistente'], show: () => true },
    ],
  },
  {
    label: 'Supervisión',
    sections: [
      { to: '/reportes', label: 'Reportes', icon: BarChart3, match: ['/reportes', '/validation', '/calibration', '/evaluation'], show: supervises },
      { to: '/audit', label: 'Auditoría', icon: History, match: ['/audit'], show: supervises },
    ],
  },
  {
    label: 'Administración',
    sections: [
      {
        to: '/configuracion',
        label: 'Configuración',
        icon: Settings,
        match: ['/configuracion', '/profiles', '/document-types', '/semantic-catalog', '/validation-rules', '/lenses', '/simulations', '/prompts', '/tools', '/users', '/sistemas', '/unidades', '/primeros-pasos'],
        show: configures,
      },
    ],
  },
]

/** The tabs of a section that has more than one list. */
export const TABS: Record<string, Page[]> = {
  cases: [
    { to: '/cases', label: 'Expedientes', description: '', icon: FolderOpen },
    { to: '/documents', label: 'Documentos', description: '', icon: FolderOpen },
    { to: '/bulk', label: 'Cargas masivas', description: '', icon: FolderOpen },
  ],
  review: [
    { to: '/review', label: 'Campos por revisar', description: '', icon: ClipboardCheck },
    { to: '/type-suggestions', label: 'Tipos de documento nuevos', description: '', icon: ClipboardCheck },
  ],
}

export const REPORTS: Page[] = [
  { to: '/validation', label: 'Observaciones de validación', description: 'Qué reglas no se cumplieron, en qué documentos y por qué.', icon: ShieldCheck },
  { to: '/calibration', label: 'Confiabilidad de la lectura', description: 'En qué datos se puede confiar sin revisarlos y en cuáles no.', icon: Gauge },
  { to: '/evaluation', label: 'Evaluación', description: 'Cuánto acierta la lectura contra documentos de respuesta conocida.', icon: FlaskConical },
]

export const SETTINGS: { label: string; pages: Page[] }[] = [
  {
    label: 'Procesos y documentos',
    pages: [
      { to: '/profiles', label: 'Procesos', description: 'Qué documentos exige cada proceso y qué reglas aplica.', icon: Workflow },
      { to: '/document-types', label: 'Tipos de documento', description: 'Los documentos que se reconocen y los datos que se leen de cada uno.', icon: BookOpen },
      { to: '/semantic-catalog', label: 'Catálogo de datos', description: 'Qué significa cada dato, venga del documento que venga.', icon: Network },
      { to: '/validation-rules', label: 'Reglas de validación', description: 'Las comprobaciones que se hacen a cada documento y expediente.', icon: ListChecks },
      { to: '/lenses', label: 'Riesgos y Legal', description: 'Resúmenes y verificación de cláusulas para cada área.', icon: Scale },
      { to: '/simulations', label: 'Probar cambios', description: 'Qué decisiones cambiarían antes de publicar una versión de un proceso.', icon: SplitSquareHorizontal, show: isAdmin },
    ],
  },
  {
    label: 'Inteligencia artificial',
    pages: [
      { to: '/prompts', label: 'Instrucciones al modelo', description: 'Lo que se le pide al modelo en cada tarea, con sus versiones.', icon: MessageSquareText, show: () => canEditPrompts() || isAdmin() },
      { to: '/tools', label: 'Catálogo de tools', description: 'Las capacidades que los agentes y sistemas pueden usar.', icon: Wrench },
    ],
  },
  {
    label: 'Accesos',
    pages: [
      { to: '/users', label: 'Personas', description: 'Quién trabaja en esta unidad y con qué rol.', icon: Users, show: isAdmin },
      { to: '/sistemas', label: 'Sistemas conectados', description: 'Los sistemas que envían expedientes y sus credenciales.', icon: KeyRound, show: isAdmin },
      { to: '/unidades', label: 'Unidades de negocio', description: 'Las unidades de la empresa y sus grupos de acceso.', icon: Building2, show: isPlatformAdmin },
    ],
  },
]

export const GETTING_STARTED: Page = {
  to: '/primeros-pasos',
  label: 'Primeros pasos',
  description: 'El orden para dejar lista una unidad y quién hace cada paso.',
  icon: Compass,
}

/** The index page a path belongs to, to offer the way back to it. */
export function hubOf(pathname: string): { to: string; label: string } | null {
  const inside = (pages: Page[]) => pages.some((p) => pathname === p.to || pathname.startsWith(`${p.to}/`))
  if (inside(REPORTS)) return { to: '/reportes', label: 'Reportes' }
  if (inside([...SETTINGS.flatMap((g) => g.pages), GETTING_STARTED])) return { to: '/configuracion', label: 'Configuración' }
  return null
}
