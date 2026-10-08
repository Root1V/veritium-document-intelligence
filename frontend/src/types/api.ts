// Hand-written interfaces mirroring the FastAPI/Pydantic response models —
// see the plan: ~10 endpoints is small enough that hand-sync beats an
// OpenAPI-codegen pipeline for now (revisit only if the surface grows).

export interface ToolCallRecord {
  turn: number
  tool_name: string
  arguments: Record<string, unknown>
  result_summary: string
  reasoning: string | null
}

/** The citation envelope wrapping every leaf value in a document's
 * `extraction` payload — page/bbox/source_text are what make this
 * platform's extraction "grounded" rather than a bare value. */
export interface Extracted<T> {
  value: T
  page: number | null
  bbox: [number, number, number, number] | null
  confidence: number
  source_text: string | null
  region_id: number | null
  reasoning_trace: ToolCallRecord[] | null
}

export interface DocumentSummary {
  id: string
  batch_id: string
  status: string
  document_type: string | null
  classification_confidence: number | null
  needs_review: boolean
  original_filename: string
  parent_document_id: string | null
  page_start: number | null
  page_end: number | null
}

export interface BatchStatusResponse {
  id: string
  status: string
  documents: DocumentSummary[]
}

export interface BatchCreateResponse {
  batch_id: string
}

export interface ValidationIssue {
  rule_id: string
  category: string
  field_path: string | null
  severity: 'info' | 'warning' | 'error'
  message: string
  confidence: number
  confidence_method: string
  explanation: string
}

export interface DocumentDetailResponse {
  id: string
  status: string
  document_type: string | null
  classification_confidence: number | null
  needs_review: boolean
  original_filename: string
  parent_document_id: string | null
  page_start: number | null
  page_end: number | null
  extraction: Record<string, unknown> | null
  validation_issues: ValidationIssue[]
}

export interface DocumentListResponse {
  total: number
  documents: DocumentSummary[]
}

export interface ReviewItem {
  id: string
  document_id: string
  field_path: string
  current_value: { value: unknown }
  confidence: number
  reason: 'low_confidence' | 'validation_issue'
  status: string
}

export interface ReviewCorrectionRequest {
  corrected_value: unknown
  model_version?: string | null
  prompt_version?: string | null
}

export interface ReviewCorrectionResponse {
  review_item_id: string
  status: string
}

export interface SuggestedField {
  name: string
  field_type: string
  description: string
  required: boolean
}

export interface TypeSuggestion {
  id: string
  document_id: string
  batch_id: string
  suggested_type_name: string
  suggested_display_name: string
  rationale: string
  fields: SuggestedField[]
  status: string
  reviewer_identity: string | null
}

export type SuggestedFieldType = 'str' | 'int' | 'float' | 'bool' | 'list'

/** Only editable while the suggestion is still "pending" — see PATCH
 * /type-suggestions/{id}. */
export interface UpdateTypeSuggestionRequest {
  suggested_type_name?: string
  suggested_display_name?: string
  fields?: { name: string; field_type: SuggestedFieldType; description: string; required: boolean }[]
}

export interface DocumentTypeFieldInfo {
  name: string
  field_type: string
  description: string | null
  required: boolean
  items?: DocumentTypeFieldInfo[] | null
}

export interface DocumentTypeInfo {
  name: string
  display_name: string
  version: number
  description: string
  fields: DocumentTypeFieldInfo[]
}

export interface PendingTypeInfo {
  suggestion_id: string
  document_id: string
  suggested_type_name: string
  suggested_display_name: string
  rationale: string
  fields: Record<string, unknown>[]
}

export interface DocumentTypeCatalogResponse {
  registered: DocumentTypeInfo[]
  pending: PendingTypeInfo[]
}

export interface AuditEntry {
  id: string
  document_id: string
  field_path: string
  reviewer_identity: string
  original_value: { value: unknown }
  corrected_value: { value: unknown }
  original_confidence: number
  model_version: string | null
  prompt_version: string | null
  timestamp: string
}

export interface AuditLogResponse {
  total: number
  entries: AuditEntry[]
}

export interface ValidationIssueEntry {
  id: string
  document_id: string | null
  document_filename: string | null
  document_type: string | null
  batch_id: string
  rule_id: string
  category: string
  field_path: string | null
  severity: 'info' | 'warning' | 'error'
  message: string
  confidence: number
  confidence_method: string
  explanation: string
  created_at: string
}

export interface ValidationLogResponse {
  total: number
  issues: ValidationIssueEntry[]
}

export type RuleKind = 'cel' | 'toggle'
export type RuleStatus = 'draft' | 'active' | 'disabled' | 'rejected'
export type RuleCelCategory = 'self' | 'request_input' | 'reference_data'

export interface ValidationRule {
  id: string
  kind: RuleKind
  rule_id: string
  category: string
  document_type: string | null
  attribute: string | null
  field_path: string | null
  description_nl: string | null
  condition_cel: string | null
  applies_when_cel: string | null
  severity: 'info' | 'warning' | 'error' | null
  message_pass: string | null
  message_fail: string | null
  rationale: string | null
  status: RuleStatus
  created_by: string | null
  reviewer_identity: string | null
  test_cases: RuleTestCase[]
}

// VRT-36: what a rule sees, and what it should give.
export interface RuleTestCase {
  name: string
  input: { value?: unknown; doc?: Record<string, unknown>; case?: Record<string, unknown>; request?: Record<string, unknown>; reference_data?: Record<string, unknown> }
  expect: 'pass' | 'fail'
}

export interface RuleTestResult {
  name: string
  expect: 'pass' | 'fail'
  got: 'pass' | 'fail' | 'error'
  detail: string | null
}

export interface DraftRuleResponse {
  outcome: 'ok' | 'ambiguous'
  questions: string[]
  rule: ValidationRule | null
}

export interface DraftRuleRequest {
  description: string
  document_type?: string
  attribute?: string
  category: RuleCelCategory
  field_path?: string
  existing_fields_hint?: string[]
}

export interface ManualRuleRequest {
  rule_id_suffix: string
  document_type?: string
  attribute?: string
  category: RuleCelCategory
  field_path?: string
  condition_cel: string
  applies_when_cel?: string
  severity: 'info' | 'warning' | 'error'
  message_pass: string
  message_fail: string
  rationale?: string
}

export interface UpdateRuleRequest {
  condition_cel?: string
  applies_when_cel?: string
  severity?: 'info' | 'warning' | 'error'
  message_pass?: string
  message_fail?: string
  field_path?: string
  test_cases?: RuleTestCase[]
}

export interface ToggleRule {
  rule_id: string
  category: string
  description: string
  status: 'active' | 'disabled'
}

export interface LoginRequest {
  email: string
  password: string
}

export type UserRole = 'admin' | 'operador' | 'visor'

export interface LoginResponse {
  access_token: string
  token_type: string
  user_name: string
  role: UserRole
}

export interface AppUser {
  id: string
  name: string
  email: string
  role: UserRole
}

export interface CreateUserRequest {
  name: string
  email: string
  password: string
  role: UserRole
}

// --- Document type catalog: new type from an example (VRT-33) -------------

export type FieldSpecType = 'str' | 'int' | 'float' | 'bool' | 'enum' | 'list'

export interface FieldSpec {
  name: string
  type: FieldSpecType
  required: boolean
  description: string | null
  enum_values?: string[] | null
  grounded?: boolean
  item_name?: string | null
  item_description?: string | null
  items?: FieldSpec[] | null
}

export interface DocumentTypeDefinition {
  key: string
  display_name: string
  description: string
  extraction_hint: string
  schema_title: string
  schema_description?: string | null
  fields: FieldSpec[]
}

export interface SemanticMappingDraft {
  field_path: string
  attribute: string
  role: string
}

export interface TypeProposal {
  definition: DocumentTypeDefinition
  mappings: SemanticMappingDraft[]
  dropped_mappings: string[]
  similar_existing_type: string | null
  key_taken: boolean
  rationale: string
}

export interface RegisterDocumentTypeRequest {
  definition: DocumentTypeDefinition
  mappings: SemanticMappingDraft[]
  suggestion_id?: string | null
}

// --- Semantic catalog (VRT-23, web in VRT-34) ------------------------------

export type SemanticDataType = 'string' | 'number' | 'integer' | 'date' | 'boolean'
export type SemanticComparison = 'identifier' | 'person_name' | 'company_name' | 'text' | 'number' | 'date'
export type PiiClass = 'none' | 'personal' | 'sensitive'

export interface SemanticEntity {
  key: string
  name: string
  definition: string
}

export interface SemanticAttribute {
  key: string
  name: string
  definition: string
  data_type: SemanticDataType
  comparison: SemanticComparison
  unit?: string | null
  format_cel?: string | null
  cardinality?: 'one' | 'many'
  pii_class: PiiClass
  tolerance?: number | null
}

export interface SemanticRole {
  key: string
  name: string
  definition: string
}

export interface FieldMapping {
  document_type: string
  field_path: string | string[]
  attribute: string
  role: string
}

export interface SemanticCatalog {
  entities: SemanticEntity[]
  attributes: SemanticAttribute[]
  roles: SemanticRole[]
  mappings: FieldMapping[]
}

export interface CatalogVersionSummary {
  id: string
  version: number
  status: 'draft' | 'published'
  content_hash: string
  created_by: string | null
  created_at: string
  published_by: string | null
  published_at: string | null
}

export interface CatalogVersionDetail extends CatalogVersionSummary {
  catalog: SemanticCatalog
}

export interface ProcessProfileSummary {
  key: string
  name: string
  active_version: number | null
  versions: { version: number; status: string; semantic_catalog_version: number }[]
}

