import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useDocument } from '@/lib/queries'
import { flattenExtraction, splitExtractionPayload } from '@/lib/extraction'
import type { BboxHighlight } from '@/components/documents/PdfViewer'
import { EvidenceViewer } from '@/components/documents/EvidenceViewer'
import { ExtractionField } from '@/components/documents/ExtractionField'
import { ExtractionTable } from '@/components/documents/ExtractionTable'
import { ValidationIssuesList } from '@/components/documents/ValidationIssuesList'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { Extracted } from '@/types/api'

export function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>()
  const { data: document, isLoading } = useDocument(documentId)

  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [showAllOnPage, setShowAllOnPage] = useState(false)
  const [currentPage, setCurrentPage] = useState(0)

  // The PDF served by /documents/{id}/file is the whole physical upload —
  // for a segment spawned by segmentation, its content starts at
  // page_start (an absolute page index into that file), not page 0. Reset
  // during render (React's documented pattern for "adjust state when a
  // prop/query result changes") rather than in an effect, which would
  // cause an extra commit.
  const [initializedForDocId, setInitializedForDocId] = useState<string | undefined>(undefined)
  if (document && document.id !== initializedForDocId) {
    setInitializedForDocId(document.id)
    setCurrentPage(document.page_start ?? 0)
    setSelectedKey(null)
  }

  const flat = useMemo(() => (document?.extraction ? flattenExtraction(document.extraction) : {}), [document])
  const { fields: allFields, tables } = useMemo(
    () => (document?.extraction ? splitExtractionPayload(document.extraction) : { fields: [], tables: [] }),
    [document],
  )
  // "summary"/"body_summary" (email_correspondence already had its own
  // summary-shaped field before this one existed) is a document overview,
  // not a field among the others — pulled out of the grid and shown as
  // prose above it instead.
  const summaryEnvelope = allFields.find(([name]) => name === 'summary' || name === 'body_summary')?.[1]
  const fields = allFields.filter(([name]) => name !== 'summary' && name !== 'body_summary')

  function selectField(key: string, envelope: Extracted<unknown>) {
    setSelectedKey(key)
    if (envelope.page !== null) setCurrentPage(envelope.page)
  }

  const highlights: BboxHighlight[] = useMemo(() => {
    const entries = Object.entries(flat).filter(([, envelope]) => envelope.page === currentPage && envelope.bbox !== null)
    const visible = showAllOnPage ? entries : entries.filter(([key]) => key === selectedKey)
    return visible.map(([key, envelope]) => ({ bbox: envelope.bbox!, active: key === selectedKey }))
  }, [flat, currentPage, selectedKey, showAllOnPage])

  if (isLoading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!document) {
    return <p className="text-muted-foreground">Documento no encontrado.</p>
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{document.original_filename}</h1>
        {document.document_type && <Badge>{document.document_type}</Badge>}
        <Badge variant="outline">{document.status}</Badge>
        {document.needs_review && <Badge variant="destructive">Requiere revisión</Badge>}
        {document.classification_confidence !== null && (
          <span className="text-xs text-muted-foreground">
            Confianza de clasificación: {(document.classification_confidence * 100).toFixed(0)}%
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-3">
          <Button variant="outline" size="sm" className="self-start" onClick={() => setShowAllOnPage((v) => !v)}>
            {showAllOnPage ? 'Mostrar solo el campo seleccionado' : 'Ver todos los campos de esta página'}
          </Button>
          <EvidenceViewer documentId={document.id} page={currentPage} onPageChange={setCurrentPage} highlights={highlights} />
        </div>

        <Tabs defaultValue="extraction" className="min-w-0">
          <TabsList>
            <TabsTrigger value="extraction">Extracción</TabsTrigger>
            <TabsTrigger value="validation">
              Validación
              {document.validation_issues.length > 0 && (
                <Badge variant="destructive" className="ml-1.5 px-1.5 py-0 text-[10px]">
                  {document.validation_issues.length}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="extraction" className="flex flex-col gap-4">
            {!document.extraction ? (
              <p className="text-sm text-muted-foreground">Sin datos extraídos.</p>
            ) : (
              <>
                {summaryEnvelope && typeof summaryEnvelope.value === 'string' && summaryEnvelope.value && (
                  <div className="rounded-lg border bg-muted/40 px-3 py-2.5">
                    <p className="text-xs font-medium text-muted-foreground">Resumen del documento</p>
                    <p className="text-sm">{summaryEnvelope.value}</p>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2">
                  {fields.map(([name, envelope]) => (
                    <ExtractionField
                      key={name}
                      name={name}
                      envelope={envelope}
                      isSelected={selectedKey === name}
                      onSelect={() => selectField(name, envelope)}
                    />
                  ))}
                </div>
                {tables.map(([name, rows]) => (
                  <ExtractionTable
                    key={name}
                    name={name}
                    rows={rows}
                    selectedKey={selectedKey}
                    onSelect={(envelope, key) => selectField(key, envelope)}
                  />
                ))}
              </>
            )}
          </TabsContent>
          <TabsContent value="validation">
            <ValidationIssuesList issues={document.validation_issues} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
