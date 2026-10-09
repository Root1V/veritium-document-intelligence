"""SQLAlchemy 2.0 ORM models. Accessed exclusively through
``persistence/repositories.py`` — no other layer builds queries directly
(repository pattern).

``tenant`` columns/keys are placeholders from day one (always "default" in
Phase 0) so Fase 1+ multi-tenancy (roadmap item 5) is an additive migration,
not a schema rewrite.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    """A reviewer's login identity. ``role`` is one of "admin" (also manages
    users), "operador" (can execute actions: upload, correct, accept/reject
    type suggestions) or "visor" (read-only) — see ``api/deps.require_role``
    for enforcement. Replaces the static ``x-api-key`` this platform used
    before the frontend module: ``reviewer_identity`` on review/type-suggestion
    actions is derived server-side from the authenticated user instead of
    trusted from the request body."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="operador", server_default="operador", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Case(Base):
    """Aggregate root (VRT-25, ADR-0002): a client's case file ("expediente")
    — the unit of work a business process hands to Veritium. It accumulates
    documents over time (each addition triggers a new ``CaseRun``), pins the
    process profile version it is evaluated under, and carries the verdict.
    Formerly ``Batch`` (table ``batches``); the legacy ``/batches`` API keeps
    working on top of it with the built-in ``ad-hoc`` profile.

    ``request_input_payload`` is the caller's process data (form fields,
    metadata) — what ``request_input`` rules and CEL's ``request`` read."""

    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("tenant", "idempotency_key", name="uq_cases_tenant_idempotency_key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    request_input_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Null only for cases created before VRT-25.
    profile_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("process_profile_versions.id"), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="backoffice", server_default="backoffice", nullable=False)  # online|backoffice|bulk
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # sha256 of the original request; a replay with the same key but a
    # different request is rejected instead of silently returning this case.
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)  # continue|human_review|return_to_client (VRT-27)
    verdict_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    verdict_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The bulk job it came in (VRT-48), if any.
    bulk_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bulk_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    documents: Mapped[list["Document"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    runs: Mapped[list["CaseRun"]] = relationship(back_populates="case", cascade="all, delete-orphan", order_by="CaseRun.run_number")
    profile_version: Mapped["ProcessProfileVersion | None"] = relationship()


class CaseRun(Base):
    """One evaluation of a case: the initial submission, or each later
    addition of documents. ``provenance`` records everything that produced
    the result (code version, profile and catalog versions, models, OCR
    backend, rule set) so a past result can be explained and reproduced.
    ``execution_ref`` is the executor's handle (an aeon run id from
    VRT-26 on)."""

    __tablename__ = "case_runs"
    __table_args__ = (UniqueConstraint("case_id", "run_number"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)  # submit | documents_added | reprocess | correction
    # What a reprocess run redoes (domain/reprocess.py::ReprocessScope);
    # None for a run that processes the whole case.
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # queued (a bulk job's run waiting for room in its lane, VRT-48) | pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)
    profile_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("process_profile_versions.id"), nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    execution_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The verdict this run produced — the case keeps only the current one.
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verdict_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="runs")


class Document(Base):
    """Entity with its own status lifecycle: uploaded -> parsing -> classifying
    -> extracting -> validating -> (needs_review | completed) | failed."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(256), nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set only on a child Document spawned by segmentation.detect_segments()
    # finding more than one logical document bundled in one physical upload
    # (e.g. an email + a payment schedule + contract T&Cs in one PDF) — the
    # parent row (the original upload) is marked status="segmented" and
    # never gets its own classification/extraction. page_start/page_end are
    # absolute page numbers into the ORIGINAL physical file, not renumbered,
    # so citations still point at the page a human reviewer would see.
    parent_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    case: Mapped["Case"] = relationship(back_populates="documents")
    extraction: Mapped["Extraction | None"] = relationship(back_populates="document", uselist=False, cascade="all, delete-orphan")
    validation_issues: Mapped[list["ValidationIssue"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    # The issues of the latest evaluation only — a new run supersedes the
    # previous run's issues instead of deleting them (audit).
    active_validation_issues: Mapped[list["ValidationIssue"]] = relationship(
        primaryjoin="and_(Document.id == ValidationIssue.document_id, ValidationIssue.superseded_at.is_(None))",
        viewonly=True,
    )
    review_items: Mapped[list["ReviewItem"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Extraction(Base):
    """1:1 with Document. ``payload`` is the JSON-serialized document-type
    schema, composed of ``Extracted[T]`` value objects (includes
    ``reasoning_trace`` when the bounded agentic loop was used)."""

    __tablename__ = "extractions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    parser_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)  # "agentic" | "fixed"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="extraction")


class ValidationIssue(Base):
    """Value object produced by the ValidationEngine — never mutated after
    creation. Covers all 5 validation categories (see validation/base.py)."""

    __tablename__ = "validation_issues"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    case_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("case_runs.id", ondelete="SET NULL"), nullable=True)
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # info|warning|error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actual: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_method: Mapped[str] = mapped_column(String(32), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set when a later run of the same case re-evaluates it (VRT-25).
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document | None"] = relationship(back_populates="validation_issues")


class ReviewItem(Base):
    """Entity with its own lifecycle: pending -> resolved."""

    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    field_path: Mapped[str] = mapped_column(String(256), nullable=False)
    current_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)  # low_confidence | validation_issue
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="review_items")
    audit_entries: Mapped[list["AuditLogEntry"]] = relationship(back_populates="review_item", cascade="all, delete-orphan")


class AuditLogEntry(Base):
    """Full correction audit trail — a first-class Phase 0 deliverable,
    deliberately not left to the calling application to bolt on later."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    review_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_items.id", ondelete="CASCADE"), nullable=False)
    original_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    original_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reviewer_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    corrected_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # VRT-39: why it was corrected (domain/correction_reasons.py) and the
    # reviewer's own words. Null only on entries from before VRT-39.
    reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    review_item: Mapped["ReviewItem"] = relationship(back_populates="audit_entries")


class DocumentTypeSuggestion(Base):
    """A drafted proposal for a new ``DocumentType``, produced when a
    document falls into 'generic' and its content looks like a stable,
    recurring business shape (see ``classification/type_discovery.py``).
    Never auto-applied: a human reviews it via GET/POST
    ``/type-suggestions`` and decides accept/reject. Accepting only marks
    the proposal actionable — it does NOT register the type in
    ``domain/document_types.py``; turning an accepted proposal into a real
    registered DocumentType (schema + extractor + prompts) remains a
    deliberate code change, same as every type added so far."""

    __tablename__ = "document_type_suggestions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    suggested_type_name: Mapped[str] = mapped_column(String(128), nullable=False)
    suggested_display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    fields: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending|accepted|rejected|registered
    reviewer_identity: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferenceEmployee(Base):
    """Minimal internal reference table backing category (d) validation
    (existence-in-database checks) via ``ReferenceDataPort``."""

    __tablename__ = "reference_employees"

    id: Mapped[uuid.UUID] = _uuid_pk()
    employee_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ValidationRuleDefinition(Base):
    """Data-driven layer on top of validation/base.py::ValidationRule,
    additive not a replacement. Two row 'kinds':

    kind="cel": a human- or LLM-drafted CEL (Common Expression Language)
    condition, deliberately scoped to categories "self", "request_input"
    and "reference_data" (existence-only) — the categories that don't
    require fuzzy-matching or a network call (see validation/rules/generic.py
    for why cross_document/external_system can't be expressed this way).
    Lifecycle: draft -> active -> disabled, or draft -> rejected. Loaded
    into DataDrivenRule instances by
    pipeline/orchestrator.py::build_default_rules whenever status="active".

    kind="toggle": an on/off switch for one of the hardcoded rule_ids from
    build_default_rules — no condition of its own (the hardcoded Python
    keeps its logic; only its enabled state becomes data-driven). status
    is "active" (enabled — the default; most rule_ids never get a row
    unless someone disables them) or "disabled".

    Rows are never hard-deleted, matching this codebase's existing
    convention for audit-relevant rows (AuditLogEntry, resolved
    DocumentTypeSuggestion) — 'deleting' a rule/toggle is a status
    transition, preserving what was tried."""

    __tablename__ = "validation_rule_definitions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # "cel" | "toggle"
    rule_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)  # null = applies to any type
    # VRT-36: a rule over a semantic attribute (e.g. 'ingreso.neto_mensual')
    # runs on every document that contributes it, whatever its type.
    attribute: Mapped[str | None] = mapped_column(String(64), nullable=True)
    field_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # VRT-36: [{name, input: {value|doc|case|request}, expect: pass|fail}];
    # activating a rule requires every case to give its expected outcome.
    test_cases: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    description_nl: Mapped[str | None] = mapped_column(Text, nullable=True)  # the human's plain-language prompt, kind="cel" only
    condition_cel: Mapped[str | None] = mapped_column(Text, nullable=True)
    applies_when_cel: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)  # info|warning|error
    message_pass: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_fail: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewer_identity: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SemanticCatalogVersion(Base):
    """One whole version of the semantic catalog (VRT-23, ADR-0007):
    entities, attributes, roles and field→attribute mappings, stored as the
    JSON of ``domain.semantic.SemanticCatalog``. Versioned as a unit and
    immutable once published — a process profile version pins one catalog
    version so a past case re-resolves identically. Lifecycle:
    draft -> published. Never hard-deleted."""

    __tablename__ = "semantic_catalog_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft", nullable=False)  # draft | published
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentTypeRecord(Base):
    """A document type of the catalog (VRT-32, ADR-0008) — e.g. 'payslip'.
    Its schema and texts live in its versions; ``key`` is what
    ``documents.document_type``, profiles and semantic mappings refer to."""

    __tablename__ = "document_types"

    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[list["DocumentTypeVersion"]] = relationship(
        back_populates="document_type", cascade="all, delete-orphan", order_by="DocumentTypeVersion.version"
    )


class DocumentTypeVersion(Base):
    """One version of a document type: the JSON of
    ``domain.document_type_catalog.DocumentTypeDefinition``. Lifecycle:
    draft -> published -> retired. Immutable once published; an extraction
    records the version that produced it (``extractions.schema_version``)."""

    __tablename__ = "document_type_versions"
    __table_args__ = (UniqueConstraint("document_type_id", "version"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_types.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft", nullable=False)  # draft | published | retired
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document_type: Mapped["DocumentTypeRecord"] = relationship(back_populates="versions")


class ProcessProfile(Base):
    """A business process that uses Veritium (VRT-24) — e.g. 'convenios'.
    Its behaviour lives in its versions; the key is the stable handle
    callers pass when creating a case."""

    __tablename__ = "process_profiles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[list["ProcessProfileVersion"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="ProcessProfileVersion.version"
    )


class ProcessProfileVersion(Base):
    """One version of a process profile: the JSON of
    ``domain.process_profile.ProcessProfileDefinition``. Lifecycle:
    draft -> published -> retired. Immutable once published — a change is a
    new version. Never hard-deleted."""

    __tablename__ = "process_profile_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("process_profiles.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft", nullable=False)  # draft | published | retired
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_catalog_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped["ProcessProfile"] = relationship(back_populates="versions")


class CaseCondition(Base):
    """A required document or evidence the case is missing (VRT-27). Opened
    by a run when a profile requirement applies and is not satisfied;
    closes itself when a later run finds it satisfied (or no longer
    applicable). An operator can waive it with a reason. Snapshots the
    requirement's label so the condition reads on its own. Never deleted."""

    __tablename__ = "case_conditions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)  # the checklist item key
    label: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # missing_document | missing_evidence
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attributes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", nullable=False)  # open | resolved | waived
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_in_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("case_runs.id", ondelete="SET NULL"), nullable=True)
    resolved_in_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("case_runs.id", ondelete="SET NULL"), nullable=True)
    resolved_by_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    waived_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    waived_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEvent(Base):
    """A domain event (VRT-28, ADR-0005), written in the same transaction as
    the change it announces — so an event is never lost nor emitted for a
    change that rolled back. ``id`` is the CloudEvents id and the
    ``webhook-id`` every delivery of it carries. ``dispatched_at`` is set
    once the event has been fanned out into deliveries."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_undispatched", "created_at", postgresql_where=text("dispatched_at IS NULL")),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    type: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. pe.veritium.case.verdict.changed
    subject: Mapped[str | None] = mapped_column(String(256), nullable=True)  # the case id
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookEndpoint(Base):
    """Where a consumer wants events delivered. The signing secret is stored
    encrypted (Fernet) and shown to the consumer only once, at creation.
    Disabling keeps the row (and its delivery history)."""

    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_types: Mapped[list] = mapped_column(JSONB, nullable=False)  # [] = all
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookDelivery(Base):
    """One event to one endpoint, with its retry state. Lifecycle:
    pending -> delivered, or pending -> dead after the retry schedule is
    exhausted (~3 days). At-least-once: a consumer deduplicates by
    ``webhook-id`` (the event id)."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "endpoint_id"),
        Index("ix_webhook_deliveries_due", "next_attempt_at", postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)  # pending|delivered|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event: Mapped["OutboxEvent"] = relationship()
    endpoint: Mapped["WebhookEndpoint"] = relationship()


class EvalSuite(Base):
    """A set of documents with the classification and field values they
    should produce (VRT-42), from a CSV/Excel table or from the human
    corrections (a golden set). Running it measures the current models,
    prompts and document types against it."""

    __tablename__ = "eval_suites"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # table | corrections
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cases: Mapped[list["EvalCase"]] = relationship(back_populates="suite", cascade="all, delete-orphan", order_by="EvalCase.position")
    runs: Mapped[list["EvalRun"]] = relationship(back_populates="suite", cascade="all, delete-orphan", order_by="EvalRun.created_at.desc()")


class EvalCase(Base):
    """One document of a suite and what it should produce. Pages are
    0-based and inclusive, for a logical document inside a larger file."""

    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = _uuid_pk()
    suite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The document a golden-set case came from (source="corrections").
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)

    suite: Mapped["EvalSuite"] = relationship(back_populates="cases")


class EvalRun(Base):
    """One measurement of a suite with the configuration of the moment,
    recorded in ``provenance`` (models, code, document type versions).
    Lifecycle: pending -> running -> completed | failed."""

    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    suite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)
    # What this run tries differently from the configuration in use, e.g.
    # {"semantic_grounding": true} (VRT-46).
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    suite: Mapped["EvalSuite"] = relationship(back_populates="runs")
    results: Mapped[list["EvalResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvalResult(Base):
    """What one case produced in one run, field by field. Written once per
    case, so a run interrupted mid-way resumes with the cases left."""

    __tablename__ = "eval_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_cases.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # done | failed
    predicted_document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # [{field, expected, actual, confidence, match}]
    field_results: Mapped[list] = mapped_column(JSONB, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["EvalRun"] = relationship(back_populates="results")


class CalibrationVersion(Base):
    """A confidence calibration computed from labelled observations
    (VRT-43). Only an admin activates one, and at most one is active: from
    then on, review routing compares the calibrated confidence with the
    threshold. Immutable once computed; a new computation is a new version."""

    __tablename__ = "calibration_versions"
    __table_args__ = (Index("ix_calibration_one_active", "status", unique=True, postgresql_where=text("status = 'active'")),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft", nullable=False)  # draft | active | retired
    # domain/calibration.py::Calibration
    model: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # where the observations came from ({"evaluation": n, "review": n}) and
    # the thresholds they suggest for a few target error rates
    report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Simulation(Base):
    """What would change if a profile version were the one in use (VRT-44).
    ``what_if`` re-decides past cases of the profile with the candidate
    version, from what was already extracted; ``shadow`` decides every new
    case of the profile with it too, alongside the real decision, until
    stopped. Neither touches a case, its verdict or its events."""

    __tablename__ = "simulations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # what_if | shadow
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("process_profile_versions.id", ondelete="CASCADE"), nullable=False)
    case_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # what_if: pending -> running -> completed | failed; shadow: running -> stopped
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile_version: Mapped["ProcessProfileVersion"] = relationship()
    results: Mapped[list["SimulationResult"]] = relationship(back_populates="simulation", cascade="all, delete-orphan")


class SimulationResult(Base):
    """One case decided with the candidate version, next to its real
    decision. In shadow mode a later run of the same case replaces it."""

    __tablename__ = "simulation_results"
    __table_args__ = (UniqueConstraint("simulation_id", "case_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    simulation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    case_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("case_runs.id", ondelete="SET NULL"), nullable=True)
    actual_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    simulated_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Reason messages the candidate adds or no longer gives.
    added_reasons: Mapped[list] = mapped_column(JSONB, nullable=False)
    removed_reasons: Mapped[list] = mapped_column(JSONB, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    simulation: Mapped["Simulation"] = relationship(back_populates="results")
    case: Mapped["Case"] = relationship()


class LensRecord(Base):
    """A lens an area uses to read cases (VRT-45): domain/lenses.py::
    LensDefinition. Editable by an admin; each result keeps the definition
    it was produced with."""

    __tablename__ = "lenses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LensResult(Base):
    """One reading of a case through a lens. Lifecycle: running -> done | failed."""

    __tablename__ = "lens_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    lens_key: Mapped[str] = mapped_column(String(64), nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", server_default="running", nullable=False)
    # domain/lenses.py::LensOutput
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromptVersionRecord(Base):
    """Every version a prompt has had (VRT-46): its text, kept the first time
    the platform runs with it, so a past run's instructions can be read even
    after the prompt changed. The base for governed editing (VRT-63)."""

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="code", server_default="code", nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptEdit(Base):
    """A change to a prompt made by an AI specialist (VRT-63), and its audit
    trail: why, by whom, which evaluation backed it, when it was published.
    Lifecycle: draft -> published -> retired, or draft -> discarded. At most
    one draft and one published edit per prompt; with none published, the
    code's text is in effect."""

    __tablename__ = "prompt_edits"
    __table_args__ = (
        Index("ix_prompt_edits_one_draft", "name", unique=True, postgresql_where=text("status = 'draft'")),
        Index("ix_prompt_edits_one_published", "name", unique=True, postgresql_where=text("status = 'published'")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The evaluation run that tried this text before it was published.
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BulkJob(Base):
    """Many cases handed over at once (VRT-48): an archive with one folder
    per case. Its cases run in the ``bulk`` lane and are released a few at a
    time, so a large job never crowds out online work. Done when none of its
    runs is left queued or in progress."""

    __tablename__ = "bulk_jobs"
    __table_args__ = (UniqueConstraint("tenant", "idempotency_key", name="uq_bulk_jobs_tenant_idempotency_key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    archive_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # What in the archive did not become a case, and why: [{reference, reason}].
    skipped: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cases: Mapped[list["Case"]] = relationship(order_by="Case.external_ref")


class UploadSession(Base):
    """A short-lived window for a person to upload a case's documents from a
    front-end (VRT-47): the calling system opens it and hands over a link;
    whoever has the link uploads and gets each file checked in seconds; on
    submit it becomes a case (or adds to one). Only the token's hash is
    kept. Lifecycle: open -> submitted, or open -> expired."""

    __tablename__ = "upload_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("process_profile_versions.id"), nullable=False)
    # Upload into an existing case instead of creating one.
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="online", server_default="online", nullable=False)
    request_input_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), nullable=True)

    profile_version: Mapped["ProcessProfileVersion"] = relationship()
    files: Mapped[list["UploadedFile"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="UploadedFile.created_at")


class UploadedFile(Base):
    """One file of an upload session and its quick check."""

    __tablename__ = "uploaded_files"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload_sessions.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # The requirement of the profile the person said it is for, if any.
    requirement_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)  # ok | warning | reject
    check_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    removed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["UploadSession"] = relationship(back_populates="files")
