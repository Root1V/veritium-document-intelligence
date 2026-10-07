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

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
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
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)  # submit | documents_added
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)  # pending|running|completed|failed
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
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending|accepted|rejected
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
    field_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
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
