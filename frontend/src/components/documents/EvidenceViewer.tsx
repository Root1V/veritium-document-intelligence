// One viewer for any uploaded document (VRT-38): PDFs through react-pdf,
// images (PNG/JPG — a phone photo of a DNI is the common case) as an image.
// Both draw the same normalized [0,1] bboxes as percentage-positioned
// boxes over the page they belong to.
import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { PdfViewer, type BboxHighlight } from '@/components/documents/PdfViewer'
import { useDocumentFile } from '@/lib/queries'
import { cn } from '@/lib/utils'

function Highlights({ highlights }: { highlights: BboxHighlight[] }) {
  return (
    <>
      {highlights.map((h, i) => {
        const [x1, y1, x2, y2] = h.bbox
        return (
          <div
            key={i}
            className={cn(
              'pointer-events-none absolute rounded-sm border-2 transition-colors',
              h.active ? 'border-primary bg-primary/20' : 'border-amber-500/70 bg-amber-400/10',
            )}
            style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }}
          />
        )
      })}
    </>
  )
}

function ImageViewer({ url, highlights, maxWidth }: { url: string; highlights: BboxHighlight[]; maxWidth: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(maxWidth)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver((entries) => setWidth(Math.min(entries[0]?.contentRect.width ?? maxWidth, maxWidth)))
    observer.observe(el)
    return () => observer.disconnect()
  }, [maxWidth])
  return (
    <div ref={ref} className="flex w-full min-w-0 justify-center">
      {/* The box is exactly the image: no border or padding inside it, so percentages map to image pixels. */}
      <div className="relative inline-block overflow-hidden rounded-lg shadow-sm ring-1 ring-border" style={{ width }}>
        <img src={url} alt="Documento" className="block w-full" />
        <Highlights highlights={highlights} />
      </div>
    </div>
  )
}

export function EvidenceViewer({
  documentId,
  page,
  onPageChange,
  highlights,
  maxWidth = 640,
}: {
  documentId: string
  page: number
  onPageChange: (page: number) => void
  highlights: BboxHighlight[]
  maxWidth?: number
}) {
  const { data: file } = useDocumentFile(documentId)
  if (!file) {
    return (
      <div className="flex h-96 items-center justify-center rounded-lg border">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }
  if (file.mimeType.startsWith('image/')) return <ImageViewer url={file.url} highlights={highlights} maxWidth={maxWidth} />
  return <PdfViewer fileUrl={file.url} page={page} onPageChange={onPageChange} highlights={highlights} maxWidth={maxWidth} />
}
