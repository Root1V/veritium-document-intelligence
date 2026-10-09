// TanStack Query hooks, one per backend endpoint — cache/loading/error
// states come from the library instead of hand-rolled state machines.
import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/apiClient'
import { getToken } from '@/lib/auth'
import type {
  BulkJobDetail,
  BulkJobSummary,
  AppUser,
  AuditLogResponse,
  BatchCreateResponse,
  BatchStatusResponse,
  CreateUserRequest,
  DocumentDetailResponse,
  DocumentListResponse,
  CaseListItem,
  CaseResult,
  CatalogVersionDetail,
  CorrectionReason,
  CorrectionSummaryRow,
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
  CalibrationDetail,
  CaseLens,
  CaseProgress,
  LensDefinition,
  LensResultView,
  CalibrationSummary,
  EvalRunDetail,
  EvalRunSummary,
  EvalSuiteDetail,
  EvalSuiteSummary,
  PromptView,
  ReprocessScope,
  SimulationDetail,
  SimulationView,
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
export function useDocumentFile(documentId: string | undefined) {
  return useQuery({
    queryKey: ['document-file', documentId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/file`, { responseType: 'blob' })
      const blob = data as Blob
      // The type decides the viewer: a PDF renders with react-pdf, an image as an image (VRT-38).
      return { url: URL.createObjectURL(blob), mimeType: blob.type }
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

export function useCases() {
  return useQuery({
    queryKey: ['cases'],
    queryFn: async () => {
      const { data } = await apiClient.get<CaseListItem[]>('/v1/cases')
      return data
    },
    // Faster while a case is moving through its steps (VRT-64).
    refetchInterval: (query) => (query.state.data?.some((c) => c.status === 'processing' || c.status === 'uploaded') ? 3_000 : 10_000),
  })
}

/** A case's progress through its steps (VRT-64), refreshed while it moves. */
export function useCaseProgress(caseId: string | undefined) {
  return useQuery({
    queryKey: ['cases', caseId, 'progress'],
    enabled: !!caseId,
    queryFn: async () => (await apiClient.get<{ status: string; progress: CaseProgress }>(`/v1/cases/${caseId}`)).data,
    refetchInterval: (query) => (query.state.data && ['processing', 'uploaded'].includes(query.state.data.status) ? 3_000 : false),
  })
}

export function useCaseResult(caseId: string | undefined) {
  return useQuery({
    queryKey: ['cases', caseId, 'result'],
    enabled: !!caseId,
    queryFn: async () => {
      const { data } = await apiClient.get<CaseResult>(`/v1/cases/${caseId}/result`)
      return data
    },
    // A case still running keeps changing; a finished one doesn't.
    refetchInterval: (query) => (query.state.data?.run?.status === 'running' || query.state.data?.run?.status === 'pending' ? 5_000 : false),
  })
}

export function useWaiveCondition() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ caseId, conditionId, reason }: { caseId: string; conditionId: string; reason: string }) => {
      const { data } = await apiClient.post(`/v1/cases/${caseId}/conditions/${conditionId}/waive`, { reason })
      return data
    },
    onSuccess: (_, { caseId }) => queryClient.invalidateQueries({ queryKey: ['cases', caseId] }),
  })
}

export type CaseExportFormat = 'json' | 'yaml' | 'markdown' | 'pdf'

/** Downloads an export of the case result (VRT-41) under the name the API gives it. */
export function downloadCaseResult(caseId: string, format: CaseExportFormat): Promise<void> {
  return downloadFile(`/v1/cases/${caseId}/result`, { format }, `expediente.${format}`)
}

/** Saves what an authenticated GET returns, under the name in its Content-Disposition. */
export async function downloadFile(path: string, params: Record<string, string>, fallbackName: string): Promise<void> {
  const response = await apiClient.get<Blob>(path, { params, responseType: 'blob' })
  const name = /filename="([^"]+)"/.exec(String(response.headers['content-disposition'] ?? ''))?.[1] ?? fallbackName
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

export function useReprocessCase() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ caseId, scope }: { caseId: string; scope: ReprocessScope }) => {
      const { data } = await apiClient.post<{ run_number: number }>(`/v1/cases/${caseId}/reprocess`, scope)
      return data
    },
    onSuccess: (_, { caseId }) => queryClient.invalidateQueries({ queryKey: ['cases', caseId] }),
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

export function useCorrectionReasons() {
  return useQuery({
    queryKey: ['review', 'reasons'],
    queryFn: async () => {
      const { data } = await apiClient.get<CorrectionReason[]>('/review/reasons')
      return data
    },
    staleTime: Infinity,
  })
}

export function useCorrectionSummary() {
  return useQuery({
    queryKey: ['audit', 'correction-summary'],
    queryFn: async () => {
      const { data } = await apiClient.get<CorrectionSummaryRow[]>('/audit/correction-summary')
      return data
    },
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

// --- Evaluation suites (VRT-42) ----------------------------------------------

const unfinished = (run: EvalRunSummary | null | undefined) => run?.status === 'pending' || run?.status === 'running'

export function useEvalSuites() {
  return useQuery({
    queryKey: ['eval-suites'],
    queryFn: async () => (await apiClient.get<EvalSuiteSummary[]>('/v1/eval-suites')).data,
    refetchInterval: (query) => (query.state.data?.some((s) => unfinished(s.latest_run)) ? 4_000 : false),
  })
}

export function useEvalSuite(suiteId: string | undefined) {
  return useQuery({
    queryKey: ['eval-suites', suiteId],
    enabled: !!suiteId,
    queryFn: async () => (await apiClient.get<EvalSuiteDetail>(`/v1/eval-suites/${suiteId}`)).data,
    refetchInterval: (query) => (query.state.data?.runs.some(unfinished) ? 4_000 : false),
  })
}

export function useEvalRun(runId: string | undefined, baselineId: string | undefined) {
  return useQuery({
    queryKey: ['eval-runs', runId, baselineId],
    enabled: !!runId,
    queryFn: async () => (await apiClient.get<EvalRunDetail>(`/v1/eval-runs/${runId}`, { params: baselineId ? { baseline: baselineId } : {} })).data,
    refetchInterval: (query) => (unfinished(query.state.data) ? 4_000 : false),
  })
}

export function useCreateEvalSuite() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, description, table, files }: { name: string; description: string; table: File; files: File[] }) => {
      const form = new FormData()
      form.append('name', name)
      if (description) form.append('description', description)
      form.append('table', table)
      files.forEach((f) => form.append('files', f))
      return (await apiClient.post<EvalSuiteDetail>('/v1/eval-suites', form)).data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['eval-suites'] }),
  })
}

export function useCreateGoldenSet() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: { name: string; description?: string }) => (await apiClient.post<EvalSuiteDetail>('/v1/eval-suites/from-corrections', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['eval-suites'] }),
  })
}

export function useRunEvalSuite() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ suiteId, semanticGrounding, promptDrafts }: { suiteId: string; semanticGrounding?: boolean; promptDrafts?: string[] }) =>
      (
        await apiClient.post<EvalRunSummary>(`/v1/eval-suites/${suiteId}/runs`, {
          ...(semanticGrounding === undefined ? {} : { semantic_grounding: semanticGrounding }),
          ...(promptDrafts?.length ? { prompt_drafts: promptDrafts } : {}),
        })
      ).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['eval-suites'] }),
  })
}

// --- Calibration (VRT-43) ----------------------------------------------------

export function useCalibrations() {
  return useQuery({
    queryKey: ['calibration'],
    queryFn: async () => (await apiClient.get<CalibrationSummary[]>('/v1/calibration')).data,
  })
}

export function useCalibration(version: number | undefined) {
  return useQuery({
    queryKey: ['calibration', version],
    enabled: version !== undefined,
    queryFn: async () => (await apiClient.get<CalibrationDetail>(`/v1/calibration/${version}`)).data,
  })
}

export function useComputeCalibration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await apiClient.post<CalibrationDetail>('/v1/calibration')).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['calibration'] }),
  })
}

export function useSetActiveCalibration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (version: number | null) =>
      (await apiClient.post(version === null ? '/v1/calibration/deactivate' : `/v1/calibration/${version}/activate`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['calibration'] }),
  })
}

// --- What-if simulation and shadow mode (VRT-44) ----------------------------

const simulating = (s: SimulationView) => s.status === 'pending' || (s.status === 'running' && s.kind === 'what_if')

export function useSimulations() {
  return useQuery({
    queryKey: ['simulations'],
    queryFn: async () => (await apiClient.get<SimulationView[]>('/v1/simulations')).data,
    refetchInterval: (query) => (query.state.data?.some(simulating) ? 3_000 : false),
  })
}

export function useSimulation(id: string | undefined) {
  return useQuery({
    queryKey: ['simulations', id],
    enabled: !!id,
    queryFn: async () => (await apiClient.get<SimulationDetail>(`/v1/simulations/${id}`)).data,
    // A running what-if fills in; a shadow grows with every new case.
    refetchInterval: (query) => (query.state.data && (simulating(query.state.data) || query.state.data.status === 'running') ? 5_000 : false),
  })
}

export function useStartSimulation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: { profile_key: string; profile_version: number; kind: 'what_if' | 'shadow'; case_limit?: number }) =>
      (await apiClient.post<SimulationView>('/v1/simulations', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['simulations'] }),
  })
}

export function useStopSimulation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => (await apiClient.post<SimulationView>(`/v1/simulations/${id}/stop`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['simulations'] }),
  })
}

// --- Lenses of Risk and Legal (VRT-45) ---------------------------------------

export function useCaseLenses(caseId: string | undefined) {
  return useQuery({
    queryKey: ['cases', caseId, 'lenses'],
    enabled: !!caseId,
    queryFn: async () => (await apiClient.get<CaseLens[]>(`/v1/cases/${caseId}/lenses`)).data,
    refetchInterval: (query) => (query.state.data?.some((l) => l.latest?.status === 'running') ? 3_000 : false),
  })
}

export function useReadWithLens() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ caseId, key }: { caseId: string; key: string }) => (await apiClient.post<LensResultView>(`/v1/cases/${caseId}/lenses/${key}`)).data,
    onSuccess: (_, { caseId }) => queryClient.invalidateQueries({ queryKey: ['cases', caseId, 'lenses'] }),
  })
}

export function useLenses() {
  return useQuery({ queryKey: ['lenses'], queryFn: async () => (await apiClient.get<LensDefinition[]>('/v1/lenses')).data })
}

export function useSaveLens() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (lens: LensDefinition) => (await apiClient.put<LensDefinition>(`/v1/lenses/${lens.key}`, lens)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['lenses'] }),
  })
}

// --- Instructions to the model (VRT-46) --------------------------------------

export function usePrompts() {
  return useQuery({ queryKey: ['prompts'], queryFn: async () => (await apiClient.get<PromptView[]>('/v1/prompts')).data })
}

// --- Governed prompt editing (VRT-63) ----------------------------------------

function usePromptAction<V>(call: (v: V) => Promise<PromptView>) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: call, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['prompts'] }) })
}

export const useSavePromptDraft = () =>
  usePromptAction(async ({ name, text, reason }: { name: string; text: string; reason: string }) => (await apiClient.put<PromptView>(`/v1/prompts/${name}/draft`, { text, reason })).data)

export const useDiscardPromptDraft = () => usePromptAction(async (name: string) => (await apiClient.delete<PromptView>(`/v1/prompts/${name}/draft`)).data)

export const usePublishPromptDraft = () =>
  usePromptAction(async ({ name, acknowledge }: { name: string; acknowledge: boolean }) =>
    (await apiClient.post<PromptView>(`/v1/prompts/${name}/draft/publish`, { acknowledge_no_evaluation: acknowledge })).data,
  )

export const useRestorePrompt = () =>
  usePromptAction(async ({ name, version, reason }: { name: string; version: string; reason: string }) =>
    (await apiClient.post<PromptView>(`/v1/prompts/${name}/restore`, { version, reason })).data,
  )

// --- Upload sessions (VRT-47) ------------------------------------------------

export function useOpenUploadSession() {
  return useMutation({
    mutationFn: async (body: { profile: string; external_ref?: string; case_id?: string }) =>
      (await apiClient.post<{ id: string; token: string; upload_url: string; expires_at: string }>('/v1/upload-sessions', body)).data,
  })
}

// --- Bulk jobs (VRT-48) --------------------------------------------------------

export function useBulkJobs() {
  return useQuery({
    queryKey: ['bulk-jobs'],
    queryFn: async () => (await apiClient.get<BulkJobSummary[]>('/v1/bulk-jobs')).data,
    refetchInterval: (query) => (query.state.data?.some((j) => !j.finished_at) ? 3_000 : 15_000),
  })
}

export function useBulkJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ['bulk-jobs', jobId],
    enabled: !!jobId,
    queryFn: async () => (await apiClient.get<BulkJobDetail>(`/v1/bulk-jobs/${jobId}`)).data,
    refetchInterval: (query) => (query.state.data && !query.state.data.finished_at ? 3_000 : false),
  })
}

export function useSubmitBulkJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ archive, profile, name }: { archive: File; profile: string; name: string }) => {
      const form = new FormData()
      form.append('archive', archive)
      if (profile) form.append('profile', profile)
      if (name) form.append('name', name)
      return (await apiClient.post<{ id: string; cases: number; skipped: BulkJobSummary['skipped'] }>('/v1/bulk-jobs', form)).data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bulk-jobs'] }),
  })
}
