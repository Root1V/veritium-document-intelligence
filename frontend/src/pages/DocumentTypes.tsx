import { Loader2 } from 'lucide-react'
import { useDocumentTypeCatalog } from '@/lib/queries'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { humanizeFieldName } from '@/lib/extraction'

export function DocumentTypesPage() {
  const { data: catalog, isLoading } = useDocumentTypeCatalog()

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Plantillas</h1>
        <p className="text-muted-foreground">
          Catálogo de tipos de documento que la plataforma reconoce y sus campos, con la versión publicada de cada uno.
          Los tipos se versionan en la base de datos (por ahora vía API <code>/v1/document-types</code>).
        </p>
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : !catalog ? (
        <p className="text-sm text-muted-foreground">No se pudo cargar el catálogo.</p>
      ) : (
        <>
          {catalog.pending.length > 0 && (
            <section className="flex flex-col gap-3">
              <h2 className="text-sm font-medium text-muted-foreground">Sugerencias aceptadas, por registrar</h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {catalog.pending.map((type) => (
                  <Card key={type.suggestion_id} className="border-dashed">
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <CardTitle className="text-base">{type.suggested_display_name}</CardTitle>
                        <Badge variant="outline">pendiente de registrar</Badge>
                      </div>
                      <CardDescription>{type.rationale}</CardDescription>
                    </CardHeader>
                  </Card>
                ))}
              </div>
            </section>
          )}

          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-medium text-muted-foreground">Tipos registrados ({catalog.registered.length})</h2>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {catalog.registered.map((type) => (
                <Card key={type.name}>
                  <CardHeader>
                    <CardTitle className="flex items-center justify-between gap-2 text-sm">
                      <span>{type.display_name}</span>
                      <Badge variant="outline" className="font-mono text-[11px]">v{type.version}</Badge>
                    </CardTitle>
                    <p className="font-mono text-xs text-muted-foreground">{type.name}</p>
                    <CardDescription>{type.description}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ul className="flex flex-wrap gap-1.5">
                      {type.fields.map((field) => (
                        <li key={field.name} title={field.description ?? undefined}>
                          <Badge variant={field.required ? 'secondary' : 'outline'} className="text-[11px]">
                            {humanizeFieldName(field.name)}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
