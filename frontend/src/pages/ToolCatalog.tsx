// The tool catalog (VRT-53): every tool Veritium's agents use or expose,
// defined once. Internal tools stay inside the extraction agent; exposed
// ones are what other agents and systems can call over MCP.
import { useState } from 'react'
import { Download, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { errorDetail } from '@/lib/apiErrors'
import { apiClient } from '@/lib/apiClient'
import { useToolCatalog } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { ToolSpec } from '@/types/api'

const COST: Record<ToolSpec['cost'], { label: string; dot: string }> = {
  ninguno: { label: 'Sin costo', dot: 'bg-emerald-500' },
  lectura: { label: 'Consulta', dot: 'bg-emerald-500' },
  modelo: { label: 'Una llamada al modelo', dot: 'bg-amber-500' },
  procesamiento: { label: 'Procesa un expediente', dot: 'bg-red-500' },
}
const ROLE: Record<string, string> = {
  visor: 'Visor',
  operador: 'Operador',
  admin: 'Admin',
  integracion: 'Integración',
  especialista_ia: 'Especialista IA',
  'agente-extraccion': 'Agente de extracción',
}
const FILTERS = [
  { key: 'all', label: 'Todas' },
  { key: 'mcp', label: 'Expuestas por MCP' },
  { key: 'internal', label: 'Internas' },
] as const

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

export function ToolCatalogPage() {
  const { data: tools, isLoading } = useToolCatalog()
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['key']>('all')
  const shown = (tools ?? []).filter((t) => filter === 'all' || t.exposure === filter)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Catálogo de tools</h1>
          <p className="text-muted-foreground">
            Las herramientas que usan los agentes de Veritium y las que ofrece a otros sistemas. Cada una se define una sola vez: qué hace, si usa un
            modelo, cuánto cuesta y quién la puede usar.
          </p>
        </div>
        <Button variant="outline" onClick={downloadDescriptors}>
          <Download className="size-4" /> Descriptores MCP
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Criterio</CardTitle>
          <CardDescription>
            Se expone por MCP solo lo que otro agente o sistema necesita como operación de negocio. Los pasos internos (clasificar, extraer, leer
            regiones de un documento) quedan dentro, para que nadie se salte el perfil del proceso ni el veredicto.
          </CardDescription>
        </CardHeader>
      </Card>

      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <Button key={f.key} size="sm" variant={filter === f.key ? 'default' : 'outline'} onClick={() => setFilter(f.key)}>
            {f.label}
            {tools && <span className="ml-1 text-xs opacity-70">{(tools ?? []).filter((t) => f.key === 'all' || t.exposure === f.key).length}</span>}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        <Card>
          <CardContent className="pt-6">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tool</TableHead>
                  <TableHead>Ficha</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((t) => (
                  <TableRow key={t.name} className="align-top">
                    <TableCell className="whitespace-normal">
                      <div className="font-medium">{t.title}</div>
                      <code className="text-xs text-muted-foreground">{t.name}</code>
                      <p className="mt-1 max-w-2xl text-xs text-muted-foreground">{t.description}</p>
                    </TableCell>
                    <TableCell className="w-64 whitespace-normal">
                      <div className="flex flex-col items-start gap-1.5 text-sm">
                        <Badge variant={t.exposure === 'mcp' ? 'secondary' : 'outline'}>
                          {t.exposure === 'mcp' ? 'Expuesta por MCP' : 'Interna'}
                        </Badge>
                        <span>
                          {t.kind === 'model' ? 'Usa un modelo' : 'Determinista'} · {t.read_only ? 'solo lee' : 'crea o cambia algo'}
                        </span>
                        <span className="flex items-center gap-1.5">
                          <span className={cn('size-2 shrink-0 rounded-full', COST[t.cost].dot)} />
                          {COST[t.cost].label}
                        </span>
                        <span className="text-xs text-muted-foreground">{t.roles.map((r) => ROLE[r] ?? r).join(', ')}</span>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
