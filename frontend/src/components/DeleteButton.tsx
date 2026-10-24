// "Eliminar" wherever something can go (VRT-72): it asks first, saying what
// goes for good, and tells whether it was deleted or — being in use — archived.
import { Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { errorDetail } from '@/lib/apiErrors'
import { useRemove } from '@/lib/queries'

interface DeleteOptions {
  path: string
  /** What will happen, in the person's words; shown before deleting. */
  question: string
  /** The reason is asked for and kept in the record (cases, documents). */
  askReason?: boolean
  onDone?: () => void
}

/** Asks first, then deletes; for a button or a menu item. */
export function useDeleteAction({ path, question, askReason = false, onDone }: DeleteOptions) {
  const remove = useRemove()
  const run = () => {
    let reason: string | undefined
    if (askReason) {
      reason = prompt(`${question}\n\n¿Por qué? (queda en el registro)`)?.trim()
      if (!reason) return
      if (reason.length < 5) return void toast.error('Indica el motivo con un poco más de detalle.')
    } else if (!confirm(question)) return
    remove.mutate(
      { path, reason },
      {
        onSuccess: (data) => {
          toast.success(
            data.outcome === 'archived' ? 'Se archivó: ya se usó, así que se conserva para la historia, pero no se usará más.' : 'Eliminado.',
          )
          onDone?.()
        },
        onError: (err) => toast.error(errorDetail(err)),
      },
    )
  }
  return { run, pending: remove.isPending }
}

export function DeleteButton({
  label = 'Eliminar',
  iconOnly = false,
  className = '',
  ...options
}: DeleteOptions & { label?: string; iconOnly?: boolean; className?: string }) {
  const { run, pending } = useDeleteAction(options)
  return (
    <Button
      size={iconOnly ? 'icon' : 'sm'}
      variant="ghost"
      className={`text-destructive ${className}`}
      aria-label={label}
      title={label}
      disabled={pending}
      onClick={(e) => {
        e.stopPropagation()
        run()
      }}
    >
      {pending ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
      {!iconOnly && label}
    </Button>
  )
}
