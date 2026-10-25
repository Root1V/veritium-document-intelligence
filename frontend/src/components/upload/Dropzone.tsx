import { useDropzone } from 'react-dropzone'
import { FileText, UploadCloud, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function Dropzone({ files, onChange }: { files: File[]; onChange: (files: File[]) => void }) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'], 'image/*': ['.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp'] },
    multiple: true,
    onDrop: (accepted) => onChange([...files, ...accepted]),
  })

  return (
    <div className="flex flex-col gap-3">
      <div
        {...getRootProps()}
        className={cn(
          'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors',
          isDragActive ? 'border-primary bg-accent' : 'border-border hover:border-primary/50',
        )}
      >
        <input {...getInputProps()} />
        <UploadCloud className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">Arrastra los documentos aquí, o haz clic para elegirlos</p>
        <p className="text-xs text-muted-foreground">Puedes subir varios archivos a la vez</p>
      </div>

      {files.length > 0 && (
        <ul className="flex flex-col gap-2">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`} className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <span className="flex-1 truncate text-sm">{file.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(file.size)}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-6"
                onClick={() => onChange(files.filter((_, i) => i !== index))}
              >
                <X className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
