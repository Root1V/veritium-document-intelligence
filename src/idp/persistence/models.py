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

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
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


class Batch(Base):
    """Aggregate root: a 'solicitud' grouping one or more documents plus an
    optional externally-supplied input payload."""

    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    request_input_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    documents: Mapped[list["Document"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class Document(Base):
    """Entity with its own status lifecycle: uploaded -> parsing -> classifying
    -> extracting -> validating -> (needs_review | completed) | failed."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
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

    batch: Mapped["Batch"] = relationship(back_populates="documents")
    extraction: Mapped["Extraction | None"] = relationship(back_populates="document", uselist=False, cascade="all, delete-orphan")
    validation_issues: Mapped[list["ValidationIssue"]] = relationship(back_populates="document", cascade="all, delete-orphan")
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
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
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
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
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
