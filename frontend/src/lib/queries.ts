// TanStack Query hooks, one per backend endpoint — cache/loading/error
// states come from the library instead of hand-rolled state machines.
import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/apiClient'
import { getToken } from '@/lib/auth'
import type {
  AppUser,
  AuditLogResponse,
  BatchCreateResponse,
  BatchStatusResponse,
  CreateUserRequest,
  DocumentDetailResponse,
  DocumentListResponse,
  CatalogVersionDetail,
  CatalogVersionSummary,
  DocumentTypeCatalogResponse,
  ProcessProfileDefinition,
  ProcessProfileSummary,
  ProfileLibrary,
  ProfileVersionDetail,
  SemanticCatalog,
  RegisterDocumentTypeRequest,
  TypeProposal,
  DraftRuleRequest,
  DraftRuleResponse,
  RuleTestResult,
  LoginRequest,
  LoginResponse,
  ManualRuleRequest,
  ReviewCorrectionRequest,
  ReviewCorrectionResponse,
  ReviewItem,
  ToggleRule,
  TypeSuggestion,
  UpdateRuleRequest,
  UpdateTypeSuggestionRequest,
  ValidationLogResponse,
  ValidationRule,
} from '@/types/api'

const TERMINAL_BATCH_STATUSES = new Set(['completed'])

export function useLogin() {
  return useMutation({
    mutationFn: async (body: LoginRequest) => {
      const { data } = await apiClient.post<LoginResponse>('/auth/login', body)
      return data
    },
  })
}

export interface DocumentListFilters {
  status?: string
  document_type?: string
  needs_review?: boolean
  /** Matches against the filename AND the extracted field values (see
   * DocumentRepository._filtered) — one box searches both. */
  q?: string
  limit?: number
  offset?: number
}

export function useDocumentList(filters: DocumentListFilters = {}) {
  return useQuery({
    queryKey: ['documents', filters],
    queryFn: async () => {
      const { data } = await apiClient.get<DocumentListResponse>('/documents', { params: filters })
      return data
    },
  })
}

export function useBatch(batchId: string | undefined) {
  return useQuery({
    queryKey: ['batch', batchId],
    queryFn: async () => {
      const { data } = await apiClient.get<BatchStatusResponse>(`/batches/${batchId}`)
      return data
    },
    enabled: !!batchId,
    // useBatchLiveUpdates (SSE) is the primary way this updates while a
    // batch is processing — this interval is only a safety net in case the
    // stream dies silently (e.g. a proxy buffering/dropping it), so it's
    // deliberately much slower than the old 2s poll.
    refetchInterval: (query) => (query.state.data?.status && TERMINAL_BATCH_STATUSES.has(query.state.data.status) ? false : 15000),
  })
}

/** Opens a Server-Sent Events connection to GET /batches/{id}/stream and
 * pushes every update straight into the ['batch', batchId] query cache —
 * every existing consumer of useBatch just re-renders, no separate state to
 * thread through. Uses `fetch` with a manual Authorization header rather
 * than the browser's native EventSource, which can't set custom headers
 * (see the backend route's docstring for why the JWT isn't passed as a
 * query param instead). No auto-reconnect loop: the backend generator ends
 * the stream on its own once the batch reaches a terminal status, and
 * useBatch's slow fallback poll above covers the rare case of the
 * connection dying for another reason. */
export function useBatchLiveUpdates(batchId: string | undefined) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!batchId) return
    const controller = new AbortController()

    async function connect() {
      const token = getToken()
      let response: Response
      try {
        response = await fetch(`/api/batches/${batchId}/stream`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        })
      } catch {
        return
      }
      const reader = response.body?.getReader()
      if (!reader) return
      const decoder = new TextDecoder()
      let buffer = ''
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const frames = buffer.split('\n\n')
          buffer = frames.pop() ?? ''
          for (const frame of frames) {
            const dataLine = frame.split('\n').find((line) => line.startsWith('data: '))
            if (!dataLine) continue
            const payload = JSON.parse(dataLine.slice('data: '.length)) as BatchStatusResponse
            queryClient.setQueryData(['batch', batchId], payload)
          }
        }
      } catch {
        // Connection dropped mid-stream — the slow fallback poll on
        // useBatch takes over rather than reconnecting here.
      }
    }

    connect()
    return () => controller.abort()
  }, [batchId, queryClient])
}

export function useCreateBatch() {
  return useMutation({
    mutationFn: async ({ files, requestInputPayload }: { files: File[]; requestInputPayload?: Record<string, unknown> }) => {
      const form = new FormData()
      for (const file of files) form.append('files', file)
      if (requestInputPayload && Object.keys(requestInputPayload).length > 0) {
        form.append('request_input_payload', JSON.stringify(requestInputPayload))
      }
      const { data } = await apiClient.post<BatchCreateResponse>('/batches', form)
      return data
    },
  })
}

export function useDocument(documentId: string | undefined) {
  return useQuery({
    queryKey: ['document', documentId],
    queryFn: async () => {
      const { data } = await apiClient.get<DocumentDetailResponse>(`/documents/${documentId}`)
      return data
    },
    enabled: !!documentId,
  })
}

/** Fetches the original file's bytes as a Blob URL, respecting the JWT
 * header — a plain `<img src=...>`/react-pdf `file=url` can't attach auth
 * headers, so the bytes are fetched through axios instead. */
export function useDocumentFileUrl(documentId: string | undefined) {
  return useQuery({
    queryKey: ['document-file', documentId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/file`, { responseType: 'blob' })
      return URL.createObjectURL(data as Blob)
    },
    enabled: !!documentId,
    staleTime: Infinity,
  })
}

export function useReviewQueue() {
  return useQuery({
    queryKey: ['review-queue'],
    queryFn: async () => {
      const { data } = await apiClient.get<ReviewItem[]>('/review')
      return data
    },
  })
}

export function useSubmitCorrection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ reviewItemId, body }: { reviewItemId: string; body: ReviewCorrectionRequest }) => {
      const { data } = await apiClient.post<ReviewCorrectionResponse>(`/review/${reviewItemId}`, body)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-queue'] })
    },
  })
}

export function useTypeSuggestions() {
  return useQuery({
    queryKey: ['type-suggestions'],
    queryFn: async () => {
      const { data } = await apiClient.get<TypeSuggestion[]>('/type-suggestions')
      return data
    },
  })
}

export function useResolveTypeSuggestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ suggestionId, decision }: { suggestionId: string; decision: 'accept' | 'reject' }) => {
      const { data } = await apiClient.post<TypeSuggestion>(`/type-suggestions/${suggestionId}/${decision}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['type-suggestions'] })
      queryClient.invalidateQueries({ queryKey: ['document-types'] })
    },
  })
}

export function useUpdateTypeSuggestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ suggestionId, body }: { suggestionId: string; body: UpdateTypeSuggestionRequest }) => {
      const { data } = await apiClient.patch<TypeSuggestion>(`/type-suggestions/${suggestionId}`, body)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['type-suggestions'] })
    },
  })
}

export function useDocumentTypeCatalog() {
  return useQuery({
    queryKey: ['document-types'],
    queryFn: async () => {
      const { data } = await apiClient.get<DocumentTypeCatalogResponse>('/document-types')
      return data
    },
  })
}

export function useProposeDocumentType() {
  return useMutation({
    mutationFn: async (input: { file?: File; documentId?: string; nameHint?: string }) => {
      const form = new FormData()
      if (input.file) form.append('file', input.file)
      if (input.documentId) form.append('document_id', input.documentId)
      if (input.nameHint) form.append('name_hint', input.nameHint)
      // OCR + one model call: tens of seconds, well past the client's default.
      const { data } = await apiClient.post<TypeProposal>('/v1/document-types/proposals', form, { timeout: 300_000 })
      return data
    },
  })
}

export function useRegisterDocumentType() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: RegisterDocumentTypeRequest) => {
      const { data } = await apiClient.post('/v1/document-types/registrations', body)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-types'] })
    },
  })
}

export function useSemanticCatalog() {
  return useQuery({
    queryKey: ['semantic-catalog', 'active'],
    queryFn: async () => {
      const { data } = await apiClient.get<CatalogVersionDetail>('/v1/semantic-catalog')
      return data
    },
  })
}

export function useProcessProfiles() {
  return useQuery({
    queryKey: ['profiles'],
    queryFn: async () => {
      const { data } = await apiClient.get<ProcessProfileSummary[]>('/v1/profiles')
      return data
    },
  })
}

export function useProfileVersion(key: string | undefined, version: number | null | undefined) {
  return useQuery({
    queryKey: ['profiles', key, version],
    enabled: !!key && !!version,
    queryFn: async () => {
      const { data } = await apiClient.get<ProfileVersionDetail>(`/v1/profiles/${key}/versions/${version}`)
      return data
    },
  })
}

export function useProfileLibrary(catalogVersion: number | undefined) {
  return useQuery({
    queryKey: ['profiles', 'library', catalogVersion],
    queryFn: async () => {
      const { data } = await apiClient.get<ProfileLibrary>('/v1/profiles/library', { params: catalogVersion ? { catalog_version: catalogVersion } : {} })
      return data
    },
  })
}

export function useSaveProfileVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { key: string; isNew: boolean; name?: string; description?: string; definition: ProcessProfileDefinition }) => {
      if (input.isNew) await apiClient.post('/v1/profiles', { key: input.key, name: input.name, description: input.description || null })
      const { data } = await apiClient.post<ProfileVersionDetail>(`/v1/profiles/${input.key}/versions`, input.definition)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['profiles'] }),
  })
}

export function usePublishProfileVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ key, version }: { key: string; version: number }) => {
      const { data } = await apiClient.post<ProfileVersionDetail>(`/v1/profiles/${key}/versions/${version}/publish`)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['profiles'] }),
  })
}

export function useSemanticCatalogVersions() {
  return useQuery({
    queryKey: ['semantic-catalog', 'versions'],
    queryFn: async () => {
      const { data } = await apiClient.get<CatalogVersionSummary[]>('/v1/semantic-catalog/versions')
      return data
    },
  })
}

export function useCreateCatalogDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (catalog: SemanticCatalog) => {
      const { data } = await apiClient.post<CatalogVersionDetail>('/v1/semantic-catalog/versions', catalog)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['semantic-catalog'] }),
  })
}

export function usePublishCatalogVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (version: number) => {
      const { data } = await apiClient.post<CatalogVersionDetail>(`/v1/semantic-catalog/versions/${version}/publish`)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['semantic-catalog'] }),
  })
}

export function useAuditLog(params: { limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: ['audit-log', params],
    queryFn: async () => {
      const { data } = await apiClient.get<AuditLogResponse>('/audit', { params })
      return data
    },
  })
}

export interface ValidationLogFilters {
  category?: string
  severity?: string
  document_type?: string
  rule_id?: string
  limit?: number
  offset?: number
}

export function useValidationLog(filters: ValidationLogFilters = {}) {
  return useQuery({
    queryKey: ['validation-log', filters],
    queryFn: async () => {
      const { data } = await apiClient.get<ValidationLogResponse>('/validation', { params: filters })
      return data
    },
  })
}

export function useUsers() {
  return useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const { data } = await apiClient.get<AppUser[]>('/users')
      return data
    },
  })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: CreateUserRequest) => {
      const { data } = await apiClient.post<AppUser>('/users', body)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
  })
}

export function useValidationRules(filters: { kind?: string; status_filter?: string } = {}) {
  return useQuery({
    queryKey: ['validation-rules', filters],
    queryFn: async () => {
      const { data } = await apiClient.get<ValidationRule[]>('/validation-rules', { params: filters })
      return data
    },
  })
}

export function useDraftValidationRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: DraftRuleRequest) => {
      const { data } = await apiClient.post<DraftRuleResponse>('/validation-rules/draft', body)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['validation-rules'] }),
  })
}

export function useCreateManualRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: ManualRuleRequest) => {
      const { data } = await apiClient.post<ValidationRule>('/validation-rules/manual', body)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['validation-rules'] }),
  })
}

export function useRunRuleTests() {
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await apiClient.post<{ results: RuleTestResult[]; all_ok: boolean }>(`/validation-rules/${id}/test`)
      return data
    },
  })
}

export function useUpdateValidationRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, body }: { id: string; body: UpdateRuleRequest }) => {
      const { data } = await apiClient.patch<ValidationRule>(`/validation-rules/${id}`, body)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['validation-rules'] }),
  })
}

export function useResolveValidationRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, decision }: { id: string; decision: 'activate' | 'reject' | 'disable' }) => {
      const { data } = await apiClient.post<ValidationRule>(`/validation-rules/${id}/${decision}`)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['validation-rules'] }),
  })
}

export function useToggleRules() {
  return useQuery({
    queryKey: ['validation-rule-toggles'],
    queryFn: async () => {
      const { data } = await apiClient.get<ToggleRule[]>('/validation-rules/toggles')
      return data
    },
  })
}

export function useSetRuleToggle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ ruleId, action }: { ruleId: string; action: 'enable' | 'disable' }) => {
      const { data } = await apiClient.post<ToggleRule>(`/validation-rules/toggles/${ruleId}/${action}`)
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['validation-rule-toggles'] }),
  })
}
