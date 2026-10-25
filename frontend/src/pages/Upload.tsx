// A case opened from the office: choose the process, see what it asks
// for, fill in the data its rules read and drop the documents. The data
// asked for is what the process actually uses (`request.<dato>` in its
// conditions, the request-input rules it binds), never a free key/value.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, Circle, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dropzone } from '@/components/upload/Dropzone'
import { errorDetail } from '@/lib/apiErrors'
import { useProcessProfiles, useProfileVersion, useSubmitCase } from '@/lib/queries'
import { humanizeFieldName } from '@/lib/extraction'
import type { ProcessProfileDefinition } from '@/types/api'

interface ProcessInput {
  label: string
  hint?: string
  options?: { value: string; label: string }[]
}

// The data a process may read, said the way an operator knows it.
const KNOWN_INPUTS: Record<string, ProcessInput> = {
  expected_employee_code: { label: 'Código de empleado', hint: 'Se compara con el de la boleta de pago.' },
  nacionalidad: {
    label: 'Nacionalidad del titular',
    options: [
      { value: 'PE', label: 'Peruana' },
      { value: 'EXT', label: 'Extranjera' },
    ],
  },
}

function inputsOf(definition: ProcessProfileDefinition): string[] {
  const keys = new Set([...JSON.stringify(definition).matchAll(/request\.(\w+)/g)].map((m) => m[1]))
  if (definition.include_all_rules || definition.rule_bindings.some((b) => b.rule_id.startsWith('request_input.'))) keys.add('expected_employee_code')
  return [...keys]
}

const processLabel = (p: { key: string; name: string }) => (p.key === 'ad-hoc' ? 'Revisión general (sin proceso definido)' : p.name)

export function UploadPage() {
  const navigate = useNavigate()
  const submit = useSubmitCase()
  const { data: profiles } = useProcessProfiles()
  const usable = (profiles ?? []).filter((p) => p.active_version !== null)
  const [chosen, setChosen] = useState('')
  const profileKey = chosen || usable.find((p) => p.key !== 'ad-hoc')?.key || usable[0]?.key || ''
  const profile = usable.find((p) => p.key === profileKey)
  const { data: version } = useProfileVersion(profile?.key, profile?.active_version)
  const [reference, setReference] = useState('')
  const [data, setData] = useState<Record<string, string>>({})
  const [files, setFiles] = useState<File[]>([])

  const definition = version?.profile_key === profileKey ? version.definition : undefined
  const inputs = definition ? inputsOf(definition) : []

  function handleSubmit() {
    const processData = Object.fromEntries(inputs.filter((k) => data[k]?.trim()).map((k) => [k, data[k].trim()]))
    submit.mutate(
      { profile: profileKey, files, externalRef: reference.trim() || undefined, processData },
      {
        onSuccess: ({ case_id }) => {
          toast.success('Expediente creado. Veritium lo está revisando.')
          navigate(`/cases/${case_id}`)
        },
        onError: (e) => toast.error(errorDetail(e)),
      },
    )
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Nuevo expediente</h1>
        <p className="text-muted-foreground">Elige el proceso, sube los documentos y Veritium te dirá si el expediente puede continuar.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>1. Proceso</CardTitle>
          <CardDescription>Define qué documentos se piden y qué se comprueba.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label>Proceso</Label>
              <Select value={profileKey} onValueChange={(v) => { setChosen(v); setData({}) }}>
                <SelectTrigger>
                  <SelectValue placeholder="Elige un proceso" />
                </SelectTrigger>
                <SelectContent>
                  {usable.map((p) => (
                    <SelectItem key={p.key} value={p.key}>
                      {processLabel(p)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="reference">N.º de solicitud (opcional)</Label>
              <Input id="reference" placeholder="p. ej. SOL-2026-0142" value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
          </div>

          {definition && definition.checklist.length > 0 && (
            <div className="flex flex-col gap-2 rounded-lg bg-muted/50 p-3">
              <span className="text-sm font-medium">Este proceso pide</span>
              <ul className="flex flex-col gap-1.5 text-sm">
                {definition.checklist.map((c) => (
                  <li key={c.key} className="flex items-start gap-2">
                    {c.required && !c.required_when_cel ? (
                      <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                    ) : (
                      <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    )}
                    <span>
                      {c.label}
                      {(!c.required || c.required_when_cel) && <span className="text-muted-foreground"> (si aplica)</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {inputs.length > 0 && (
            <div className="grid gap-4 sm:grid-cols-2">
              {inputs.map((key) => {
                const known = KNOWN_INPUTS[key]
                const label = known?.label ?? humanizeFieldName(key)
                return (
                  <div key={key} className="flex flex-col gap-2">
                    <Label htmlFor={`in-${key}`}>{label}</Label>
                    {known?.options ? (
                      <Select value={data[key] ?? ''} onValueChange={(v) => setData({ ...data, [key]: v })}>
                        <SelectTrigger id={`in-${key}`}>
                          <SelectValue placeholder="Elige" />
                        </SelectTrigger>
                        <SelectContent>
                          {known.options.map((o) => (
                            <SelectItem key={o.value} value={o.value}>
                              {o.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input id={`in-${key}`} value={data[key] ?? ''} onChange={(e) => setData({ ...data, [key]: e.target.value })} />
                    )}
                    {known?.hint && <p className="text-xs text-muted-foreground">{known.hint}</p>}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>2. Documentos</CardTitle>
          <CardDescription>PDF o fotos. Puede ir todo en un solo archivo: Veritium separa y reconoce cada documento.</CardDescription>
        </CardHeader>
        <CardContent>
          <Dropzone files={files} onChange={setFiles} />
        </CardContent>
      </Card>

      <Button size="lg" className="self-start" disabled={!profileKey || files.length === 0 || submit.isPending} onClick={handleSubmit}>
        {submit.isPending && <Loader2 className="size-4 animate-spin" />}
        Enviar a revisión
      </Button>
    </div>
  )
}
