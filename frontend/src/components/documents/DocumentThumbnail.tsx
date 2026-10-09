// A small first-page preview per identified document — lets a reviewer see
// at a glance that one physical upload contained several logical documents
// (segmentation) without opening each one. PDFs render via react-pdf,
// images as images (VRT-38).
import { Document, Page } from 'react-pdf'
import { Loader2 } from 'lucide-react'
import { useDocumentFile } from '@/lib/queries'

export function DocumentThumbnail({ documentId, page }: { documentId: string; page: number }) {
  const { data: file } = useDocumentFile(documentId)

  if (!file) {
    return (
      <div className="flex h-32 w-24 items-center justify-center rounded border bg-muted">
        <Loader2 className="size-4 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded border">
      {file.mimeType.startsWith('image/') ? (
        <img src={file.url} alt="" className="block w-24" />
      ) : (
        <Document file={file.url} loading={<div className="h-32 w-24" />}>
          <Page pageNumber={page + 1} width={96} />
        </Document>
      )}
    </div>
  )
}
