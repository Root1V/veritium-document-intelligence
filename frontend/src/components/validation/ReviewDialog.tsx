// Reviewing a finding without leaving the page (VRT-105): the same row as
// the review queue — correct the datum, confirm it as it is, or use what the
// AI suggests. When it leaves the queue, it is done.
import { useEffect } from 'react'
import { CircleCheck, Loader2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useReviewQueue } from '@/lib/queries'
import { ReviewRow } from '@/pages/ReviewQueue'

export function ReviewDialog({ reviewItemId, finding, onClose }: { reviewItemId: string; finding: string; onClose: () => void }) {
  const { data: queue, isLoading } = useReviewQueue()
  const queryClient = useQueryClient()
  const item = queue?.find((i) => i.id === reviewItemId)
  const done = !isLoading && !item

  useEffect(() => {
    if (done) queryClient.invalidateQueries({ queryKey: ['validation-log'] })
  }, [done, queryClient])

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>Revisar la observación</DialogTitle>
          <DialogDescription>{finding}</DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-6 py-5">
          {isLoading ? (
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          ) : item ? (
            <>
              <p className="text-sm text-muted-foreground">
                Si el documento se leyó mal, <strong className="text-foreground">corrige</strong> el dato. Si el documento de verdad dice eso,{' '}
                <strong className="text-foreground">descarta la observación</strong> diciendo por qué. Las dos quedan en la auditoría.
              </p>
              <ReviewRow item={item} />
            </>
          ) : (
            <div className="flex flex-col items-center gap-3 py-6 text-center">
              <CircleCheck className="size-8 text-emerald-600" />
              <p className="text-sm">Listo: esta observación ya está revisada.</p>
              <Button onClick={onClose}>Cerrar</Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
