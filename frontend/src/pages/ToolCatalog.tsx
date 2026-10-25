// The tool catalog (VRT-53, VRT-95): every tool Veritium's agents use or
// expose, defined once. Exposed ones are what other agents and systems can
// call over MCP, grouped by what they are for; internal ones stay inside the
// agent that uses them. The technical name and descriptor stay folded.
import { useState, type ReactNode } from 'react'
import { Bot, Download, Eye, FileSearch, FolderInput, Loader2, PencilLine, Plug, Scale, Search, Sparkles, type LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { errorDetail } from '@/lib/apiErrors'
import { apiClient } from '@/lib/apiClient'
import { useToolCatalog } from '@/lib/queries'
import { COST, GROUPS, ROLE, SUMMARY, groupOf, type ToolGroup } from '@/lib/tools'
import { cn } from '@/lib/utils'
import type { ToolSpec } from '@/types/api'

const GROUP_ICON: Record<ToolGroup, LucideIcon> = { cases: FolderInput, consult: FileSearch, areas: Scale, extraction: Bot, investigation: Search, other: Bot }
type Filter = 'all' | ToolSpec['exposure']

async function downloadDescriptors() {
  try {
    const { data } = await apiClient.get('/v1/tools/mcp')
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    link.download = 'veritium-tools-mcp.json'
    link.click()
    URL.revokeObjectURL(link.href)
  } catch (e) {
    toast.error(errorDetail(e))
  }
}

// Descriptions name parameters between backticks, as other agents read them.
function Described({ text }: { text: string }) {
  return (
    <p className="whitespace-normal">
      {text.split('`').map((part, i) => (i % 2 ? <code key={i} className="rounded bg-muted px-1 text-xs text-foreground">{part}</code> : part))}
    </p>
  )
}

function Chip({ icon: Icon, children, tone }: { icon?: LucideIcon; children: ReactNode; tone?: 'ai' }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium', tone === 'ai' ? 'bg-violet-500/10 text-violet-700 dark:text-violet-300' : 'bg-muted text-muted-foreground')}>
      {Icon && <Icon className="size-3" />} {children}
    </span>
  )
}

function ToolCard({ tool }: { tool: ToolSpec }) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-col gap-1">
        <span className="font-semibold">{tool.title}</span>
        <p className="text-sm text-muted-foreground">{SUMMARY[tool.name] ?? tool.description}</p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {tool.kind === 'model' ? (
          <Chip icon={Sparkles} tone="ai">
            Usa IA
          </Chip>
        ) : (
          <Chip>Sin IA</Chip>
        )}
        {tool.read_only ? <Chip icon={Eye}>Solo consulta</Chip> : <Chip icon={PencilLine}>Crea o cambia algo</Chip>}
        <span className="inline-flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
          <span className={cn('size-2 shrink-0 rounded-full', COST[tool.cost].dot)} /> {COST[tool.cost].label}
        </span>
      </div>
      <div className="mt-auto flex flex-col gap-2 border-t pt-3 text-xs text-muted-foreground">
        <span>
          <span className="font-medium text-foreground">Quién la usa:</span> {tool.roles.map((r) => ROLE[r] ?? r).join(', ')}
        </span>
        <details className="group">
          <summary className="cursor-pointer select-none hover:text-foreground">Detalle técnico</summary>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt>Para el agente</dt>
            <dd>
              <Described text={tool.description} />
            </dd>
            <dt>Nombre</dt>
            <dd>
              <code className="text-foreground">{tool.name}</code>
            </dd>
            <dt>Disponible</dt>
            <dd>{tool.exposure === 'mcp' ? 'Por MCP, para otros sistemas' : 'Solo dentro de Veritium'}</dd>
            <dt>Repetirla</dt>
            <dd>{tool.idempotent ? 'No duplica nada' : 'Cada llamada cuenta'}</dd>
          </dl>
        </details>
      </div>
    </div>
  )
}

export function ToolCatalogPage() {
  const { data: tools, isLoading, isError } = useToolCatalog()
  const [filter, setFilter] = useState<Filter>('all')
  const [onlyAi, setOnlyAi] = useState(false)
  const [query, setQuery] = useState('')
  const all = tools ?? []
  const q = query.trim().toLocaleLowerCase('es')
  const shown = all.filter(
    (t) =>
      (filter === 'all' || t.exposure === filter) &&
      (!onlyAi || t.kind === 'model') &&
      (!q || `${t.title} ${SUMMARY[t.name] ?? ''} ${t.description} ${t.name}`.toLocaleLowerCase('es').includes(q)),
  )
  const count = (exposure: ToolSpec['exposure']) => all.filter((t) => t.exposure === exposure).length

  const SIDES: { key: ToolSpec['exposure']; icon: LucideIcon; name: string; hint: string }[] = [
    { key: 'mcp', icon: Plug, name: 'Para otros sistemas', hint: 'Operaciones de negocio que otro agente o sistema puede pedir. Siempre pasan por el proceso y su decisión.' },
    { key: 'internal', icon: Bot, name: 'Internas', hint: 'Pasos de los agentes de Veritium. Nadie de fuera puede llamarlos ni saltarse la decisión.' },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Herramientas para agentes</h1>
          <p className="text-muted-foreground">Lo que pueden hacer los agentes de Veritium y los sistemas que se conectan a él: qué hace cada herramienta, si usa IA y quién la puede usar.</p>
        </div>
        <Button variant="outline" onClick={downloadDescriptors} title="Descriptores MCP, para conectar otro agente o sistema">
          <Download className="size-4" /> Ficha técnica
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {SIDES.map((s) => {
          const active = filter === s.key
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => setFilter(active ? 'all' : s.key)}
              className={cn('flex items-start gap-3 rounded-xl border bg-card p-4 text-left transition hover:border-primary/40', active && 'border-primary ring-1 ring-primary')}
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <s.icon className="size-5" />
              </span>
              <span className="flex flex-col gap-0.5">
                <span className="flex items-baseline gap-2">
                  <span className="font-semibold">{s.name}</span>
                  {tools && <span className="text-sm text-muted-foreground">{count(s.key)}</span>}
                </span>
                <span className="text-sm text-muted-foreground">{s.hint}</span>
              </span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar una herramienta" className="pl-8" />
        </div>
        <Button size="sm" variant={onlyAi ? 'default' : 'outline'} onClick={() => setOnlyAi(!onlyAi)}>
          <Sparkles className="size-3.5" /> Solo las que usan IA
        </Button>
        {(filter !== 'all' || onlyAi || q) && (
          <Button size="sm" variant="ghost" onClick={() => (setFilter('all'), setOnlyAi(false), setQuery(''))}>
            Ver todas
          </Button>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">No se pudieron cargar las herramientas: el servidor de Veritium no responde.</p>
      ) : !shown.length ? (
        <p className="text-sm text-muted-foreground">Ninguna herramienta coincide con la búsqueda.</p>
      ) : (
        GROUPS.map((g) => {
          const list = shown.filter((t) => groupOf(t) === g.key)
          if (!list.length) return null
          const Icon = GROUP_ICON[g.key]
          return (
            <section key={g.key} className="rounded-2xl border bg-muted/40">
              <div className="flex flex-wrap items-center gap-3 rounded-t-2xl border-b bg-background px-4 py-3 sm:px-5">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                  <Icon className="size-5" />
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-xl font-semibold tracking-tight">{g.name}</h2>
                    <span className="rounded-full bg-background px-2 py-0.5 text-xs font-medium text-muted-foreground ring-1 ring-border">
                      {list.length === 1 ? '1 herramienta' : `${list.length} herramientas`}
                    </span>
                    <span className="text-xs text-muted-foreground">· {g.exposure === 'mcp' ? 'para otros sistemas' : 'interna'}</span>
                  </div>
                  {g.hint && <p className="text-sm text-muted-foreground">{g.hint}</p>}
                </div>
              </div>
              <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-2 2xl:grid-cols-3">
                {list.map((t) => (
                  <ToolCard key={t.name} tool={t} />
                ))}
              </div>
            </section>
          )
        })
      )}
    </div>
  )
}
