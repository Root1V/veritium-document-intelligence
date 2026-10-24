import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dropzone } from '@/components/upload/Dropzone'
import { RequestInputForm, type ExtraField } from '@/components/upload/RequestInputForm'
import { useCreateBatch } from '@/lib/queries'

export function UploadPage() {
  const navigate = useNavigate()
  const createBatch = useCreateBatch()
  const [files, setFiles] = useState<File[]>([])
  const [expectedEmployeeCode, setExpectedEmployeeCode] = useState('')
  const [extraFields, setExtraFields] = useState<ExtraField[]>([])

  function handleSubmit() {
    if (files.length === 0) {
      toast.error('Agrega al menos un documento.')
      return
    }
    const payload: Record<string, unknown> = {}
    if (expectedEmployeeCode.trim()) payload.expected_employee_code = expectedEmployeeCode.trim()
    for (const field of extraFields) {
      if (field.key.trim()) payload[field.key.trim()] = field.value
    }

    createBatch.mutate(
      { files, requestInputPayload: payload },
      {
        onSuccess: (data) => {
          toast.success('Solicitud creada, procesando...')
          navigate(`/batches/${data.batch_id}`)
        },
        onError: () => toast.error('No se pudo crear la solicitud.'),
      },
    )
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Nuevo expediente</h1>
        <p className="text-muted-foreground">
          Sube uno o más documentos de una solicitud. Se procesan automáticamente: segmentación, clasificación,
          extracción y validación.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Documentos</CardTitle>
          <CardDescription>Formato PDF.</CardDescription>
        </CardHeader>
        <CardContent>
          <Dropzone files={files} onChange={setFiles} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Datos de entrada</CardTitle>
          <CardDescription>Se usan para validar contra lo extraído de los documentos.</CardDescription>
        </CardHeader>
        <CardContent>
          <RequestInputForm
            expectedEmployeeCode={expectedEmployeeCode}
            onExpectedEmployeeCodeChange={setExpectedEmployeeCode}
            extraFields={extraFields}
            onExtraFieldsChange={setExtraFields}
          />
        </CardContent>
      </Card>

      <Button size="lg" className="self-start" disabled={createBatch.isPending} onClick={handleSubmit}>
        {createBatch.isPending && <Loader2 className="size-4 animate-spin" />}
        Procesar documentos
      </Button>
    </div>
  )
}
