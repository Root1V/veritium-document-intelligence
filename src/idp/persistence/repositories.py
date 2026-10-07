"""Repository pattern: the only layer allowed to build SQLAlchemy queries.
Domain/service code depends on these, never on ``models.py`` + raw queries
directly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Text, func, or_, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from idp.domain.semantic import SemanticCatalog
from idp.domain.semantic_seed import seed_catalog
from idp.persistence.models import (
    AuditLogEntry,
    Batch,
    Document,
    DocumentTypeSuggestion,
    Extraction,
    ReferenceEmployee,
    ReviewItem,
    SemanticCatalogVersion,
    User,
    ValidationIssue,
    ValidationRuleDefinition,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, *, name: str, email: str, password_hash: str, role: str = "operador") -> User:
        user = User(name=name, email=email, password_hash=password_hash, role=role)
        self._session.add(user)
        await self._session.flush()
        return user

    async def list(self) -> list[User]:
        result = await self._session.execute(select(User).order_by(User.created_at))
        return list(result.scalars().all())


class BatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, tenant: str = "default", request_input_payload: dict | None = None) -> Batch:
        batch = Batch(tenant=tenant, request_input_payload=request_input_payload)
        self._session.add(batch)
        await self._session.flush()
        return batch

    async def get(self, batch_id: uuid.UUID) -> Batch | None:
        # populate_existing=True — see DocumentRepository.get() for why this
        # is required, not optional: without it, polling GET /batches/{id}
        # within the same session as an in-flight pipeline run can return
        # stale (pre-extraction) document/relationship state.
        stmt = (
            select(Batch)
            .where(Batch.id == batch_id)
            .options(
                selectinload(Batch.documents).selectinload(Document.extraction),
                selectinload(Batch.documents).selectinload(Document.validation_issues),
            )
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_status(self, batch_id: uuid.UUID, status: str) -> None:
        batch = await self._session.get(Batch, batch_id)
        if batch is not None:
            batch.status = status


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, batch_id: uuid.UUID, storage_key: str, original_filename: str) -> Document:
        doc = Document(batch_id=batch_id, storage_key=storage_key, original_filename=original_filename)
        self._session.add(doc)
        await self._session.flush()
        return doc

    async def create_child(
        self, *, batch_id: uuid.UUID, parent_document_id: uuid.UUID, storage_key: str, original_filename: str, page_start: int, page_end: int
    ) -> Document:
        """One logical document spawned by segmentation from a physical
        upload that bundled more than one — same storage_key as the parent
        (no re-upload needed, it's the same file), scoped to its page range."""
        doc = Document(
            batch_id=batch_id,
            storage_key=storage_key,
            original_filename=original_filename,
            parent_document_id=parent_document_id,
            page_start=page_start,
            page_end=page_end,
        )
        self._session.add(doc)
        await self._session.flush()
        return doc

    async def get(self, document_id: uuid.UUID) -> Document | None:
        # populate_existing=True: without it, SQLAlchemy's identity map can
        # return an already-loaded Document from earlier in the same session
        # with a stale (e.g. still-None) `.extraction` relationship, even
        # though an Extraction row was inserted afterward — because that
        # insert never touched this Document instance's Python-side
        # relationship attribute, only the FK on the new row.
        stmt = (
            select(Document)
            .where(Document.id == document_id)
            .options(
                selectinload(Document.extraction),
                selectinload(Document.validation_issues),
                selectinload(Document.review_items),
            )
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_batch(self, batch_id: uuid.UUID) -> list[Document]:
        stmt = select(Document).where(Document.batch_id == batch_id).options(selectinload(Document.extraction))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _filtered(stmt, *, status: str | None, document_type: str | None, needs_review: bool | None, q: str | None):
        if status is not None:
            stmt = stmt.where(Document.status == status)
        if document_type is not None:
            stmt = stmt.where(Document.document_type == document_type)
        if needs_review is not None:
            stmt = stmt.where(Document.needs_review == needs_review)
        if q:
            # Extraction is 1:1 with Document (unique FK) so this outer join
            # never duplicates rows. Casting the whole JSONB payload to text
            # and substring-matching is crude (no relevance ranking, no
            # index) but correct across all 12+ document type schemas
            # without needing per-type field lists — fine at this corpus
            # size; revisit with a tsvector/GIN index only if it's ever
            # actually slow.
            like = f"%{q}%"
            stmt = stmt.outerjoin(Extraction, Extraction.document_id == Document.id).where(
                or_(Document.original_filename.ilike(like), sa_cast(Extraction.payload, Text).ilike(like))
            )
        return stmt

    async def list(
        self,
        *,
        status: str | None = None,
        document_type: str | None = None,
        needs_review: bool | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        stmt = select(Document).order_by(Document.created_at.desc()).limit(limit).offset(offset)
        stmt = self._filtered(stmt, status=status, document_type=document_type, needs_review=needs_review, q=q)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        *,
        status: str | None = None,
        document_type: str | None = None,
        needs_review: bool | None = None,
        q: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Document)
        stmt = self._filtered(stmt, status=status, document_type=document_type, needs_review=needs_review, q=q)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def set_classification(self, document_id: uuid.UUID, *, document_type: str, confidence: float, reasoning: str, needs_review: bool) -> None:
        doc = await self._session.get(Document, document_id)
        if doc is not None:
            doc.document_type = document_type
            doc.classification_confidence = confidence
            doc.classification_reasoning = reasoning
            doc.needs_review = doc.needs_review or needs_review

    async def set_status(self, document_id: uuid.UUID, status: str) -> None:
        doc = await self._session.get(Document, document_id)
        if doc is not None:
            doc.status = status

    async def mark_needs_review(self, document_id: uuid.UUID) -> None:
        doc = await self._session.get(Document, document_id)
        if doc is not None:
            doc.needs_review = True


class ExtractionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, *, document_id: uuid.UUID, schema_version: str, payload: dict, parser_backend: str, extraction_method: str) -> Extraction:
        extraction = Extraction(
            document_id=document_id,
            schema_version=schema_version,
            payload=payload,
            parser_backend=parser_backend,
            extraction_method=extraction_method,
        )
        self._session.add(extraction)
        await self._session.flush()
        return extraction


class ValidationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_issue(self, issue: ValidationIssue) -> ValidationIssue:
        self._session.add(issue)
        await self._session.flush()
        return issue

    async def list_for_batch(self, batch_id: uuid.UUID) -> list[ValidationIssue]:
        stmt = select(ValidationIssue).where(ValidationIssue.batch_id == batch_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _filtered(stmt, *, category: str | None, severity: str | None, rule_id: str | None, document_type: str | None):
        if category is not None:
            stmt = stmt.where(ValidationIssue.category == category)
        if severity is not None:
            stmt = stmt.where(ValidationIssue.severity == severity)
        if rule_id is not None:
            stmt = stmt.where(ValidationIssue.rule_id == rule_id)
        if document_type is not None:
            # Only ValidationIssue rows tied to a real document can match a
            # document_type filter — no rows here are batch-only today, but
            # the FK is nullable (see the model), so an inner join is
            # correct: it's fine for this filter to exclude those.
            stmt = stmt.join(Document, Document.id == ValidationIssue.document_id).where(Document.document_type == document_type)
        return stmt

    async def list(
        self,
        *,
        category: str | None = None,
        severity: str | None = None,
        rule_id: str | None = None,
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ValidationIssue]:
        stmt = (
            select(ValidationIssue)
            .options(selectinload(ValidationIssue.document))
            .order_by(ValidationIssue.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        stmt = self._filtered(stmt, category=category, severity=severity, rule_id=rule_id, document_type=document_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        *,
        category: str | None = None,
        severity: str | None = None,
        rule_id: str | None = None,
        document_type: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(ValidationIssue)
        stmt = self._filtered(stmt, category=category, severity=severity, rule_id=rule_id, document_type=document_type)
        result = await self._session.execute(stmt)
        return result.scalar_one()


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_item(self, item: ReviewItem) -> ReviewItem:
        self._session.add(item)
        await self._session.flush()
        return item

    async def list_pending(self) -> list[ReviewItem]:
        stmt = select(ReviewItem).where(ReviewItem.status == "pending")
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, review_item_id: uuid.UUID) -> ReviewItem | None:
        return await self._session.get(ReviewItem, review_item_id)

    async def resolve(self, review_item_id: uuid.UUID, *, reviewer_identity: str, corrected_value: dict, model_version: str | None = None, prompt_version: str | None = None) -> AuditLogEntry:
        item = await self._session.get(ReviewItem, review_item_id)
        if item is None:
            raise ValueError(f"review item not found: {review_item_id}")
        entry = AuditLogEntry(
            review_item_id=item.id,
            original_value=item.current_value,
            original_confidence=item.confidence,
            reviewer_identity=reviewer_identity,
            corrected_value=corrected_value,
            model_version=model_version,
            prompt_version=prompt_version,
        )
        item.status = "resolved"
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def list_audit_entries(self, *, limit: int = 50, offset: int = 0) -> list[AuditLogEntry]:
        # selectinload(review_item) avoids an N+1 — the API response needs
        # document_id/field_path off the parent ReviewItem for every row.
        stmt = (
            select(AuditLogEntry)
            .options(selectinload(AuditLogEntry.review_item))
            .order_by(AuditLogEntry.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_audit_entries(self) -> int:
        stmt = select(func.count()).select_from(AuditLogEntry)
        result = await self._session.execute(stmt)
        return result.scalar_one()


class TypeSuggestionRepository:
    """Backs ``api/routes/type_suggestions.py`` — the human-review queue
    for drafted ``DocumentType`` proposals (see
    ``classification/type_discovery.py``)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        document_id: uuid.UUID,
        batch_id: uuid.UUID,
        suggested_type_name: str,
        suggested_display_name: str,
        rationale: str,
        fields: list[dict],
    ) -> DocumentTypeSuggestion:
        row = DocumentTypeSuggestion(
            document_id=document_id,
            batch_id=batch_id,
            suggested_type_name=suggested_type_name,
            suggested_display_name=suggested_display_name,
            rationale=rationale,
            fields=fields,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_pending(self) -> list[DocumentTypeSuggestion]:
        return await self.list_by_status("pending")

    async def list_by_status(self, status: str) -> list[DocumentTypeSuggestion]:
        stmt = select(DocumentTypeSuggestion).where(DocumentTypeSuggestion.status == status)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, suggestion_id: uuid.UUID) -> DocumentTypeSuggestion | None:
        return await self._session.get(DocumentTypeSuggestion, suggestion_id)

    async def resolve(self, suggestion_id: uuid.UUID, *, decision: str, reviewer_identity: str) -> DocumentTypeSuggestion:
        row = await self._session.get(DocumentTypeSuggestion, suggestion_id)
        if row is None:
            raise ValueError(f"type suggestion not found: {suggestion_id}")
        row.status = decision
        row.reviewer_identity = reviewer_identity
        row.reviewed_at = datetime.now(UTC)
        await self._session.flush()
        return row

    async def update(
        self,
        suggestion_id: uuid.UUID,
        *,
        suggested_type_name: str | None = None,
        suggested_display_name: str | None = None,
        fields: list[dict] | None = None,
    ) -> DocumentTypeSuggestion:
        """Refines a still-pending proposal (rename/retype/add/remove
        fields) before a human decides accept/reject — never touches a
        type already registered in code, see api/routes/type_suggestions.py."""
        row = await self._session.get(DocumentTypeSuggestion, suggestion_id)
        if row is None:
            raise ValueError(f"type suggestion not found: {suggestion_id}")
        if suggested_type_name is not None:
            row.suggested_type_name = suggested_type_name
        if suggested_display_name is not None:
            row.suggested_display_name = suggested_display_name
        if fields is not None:
            row.fields = fields
        await self._session.flush()
        return row


class ValidationRuleRepository:
    """Backs api/routes/validation_rules.py and
    pipeline/orchestrator.py::build_default_rules. Two row kinds — see
    persistence/models.py::ValidationRuleDefinition's docstring."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_cel_draft(
        self,
        *,
        rule_id: str,
        category: str,
        document_type: str | None,
        field_path: str | None,
        description_nl: str | None,
        condition_cel: str,
        applies_when_cel: str | None,
        severity: str,
        message_pass: str,
        message_fail: str,
        rationale: str | None,
        created_by: str,
    ) -> ValidationRuleDefinition:
        row = ValidationRuleDefinition(
            kind="cel",
            rule_id=rule_id,
            category=category,
            document_type=document_type,
            field_path=field_path,
            description_nl=description_nl,
            condition_cel=condition_cel,
            applies_when_cel=applies_when_cel,
            severity=severity,
            message_pass=message_pass,
            message_fail=message_fail,
            rationale=rationale,
            status="draft",
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_or_create_toggle(self, *, rule_id: str, category: str) -> ValidationRuleDefinition:
        """Idempotent: a hardcoded rule_id has no row at all until the
        first time someone disables it. GET /validation-rules/toggles
        synthesizes a virtual 'active' row for any hardcoded rule_id with
        no row yet, so the frontend never needs to distinguish 'no row'
        from 'row with status=active'."""
        existing = await self.get_by_rule_id(rule_id)
        if existing is not None:
            return existing
        row = ValidationRuleDefinition(kind="toggle", rule_id=rule_id, category=category, status="active")
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, definition_id: uuid.UUID) -> ValidationRuleDefinition | None:
        return await self._session.get(ValidationRuleDefinition, definition_id)

    async def get_by_rule_id(self, rule_id: str) -> ValidationRuleDefinition | None:
        stmt = select(ValidationRuleDefinition).where(ValidationRuleDefinition.rule_id == rule_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_status(self, status: str, *, kind: str | None = None) -> list[ValidationRuleDefinition]:
        stmt = select(ValidationRuleDefinition).where(ValidationRuleDefinition.status == status)
        if kind is not None:
            stmt = stmt.where(ValidationRuleDefinition.kind == kind)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, *, kind: str | None = None) -> list[ValidationRuleDefinition]:
        stmt = select(ValidationRuleDefinition)
        if kind is not None:
            stmt = stmt.where(ValidationRuleDefinition.kind == kind)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active_cel_rules(self) -> list[ValidationRuleDefinition]:
        return await self.list_by_status("active", kind="cel")

    async def list_disabled_toggle_rule_ids(self) -> set[str]:
        rows = await self.list_by_status("disabled", kind="toggle")
        return {row.rule_id for row in rows}

    async def update_draft(
        self,
        definition_id: uuid.UUID,
        *,
        condition_cel: str | None = None,
        applies_when_cel: str | None = None,
        severity: str | None = None,
        message_pass: str | None = None,
        message_fail: str | None = None,
        field_path: str | None = None,
    ) -> ValidationRuleDefinition:
        """Refines a still-draft kind="cel" row before activation — the
        caller (api/routes/validation_rules.py) is responsible for
        rejecting the call when the row isn't status="draft", same split
        of responsibility as TypeSuggestionRepository.update."""
        row = await self._session.get(ValidationRuleDefinition, definition_id)
        if row is None:
            raise ValueError(f"validation rule definition not found: {definition_id}")
        if condition_cel is not None:
            row.condition_cel = condition_cel
        if applies_when_cel is not None:
            row.applies_when_cel = applies_when_cel
        if severity is not None:
            row.severity = severity
        if message_pass is not None:
            row.message_pass = message_pass
        if message_fail is not None:
            row.message_fail = message_fail
        if field_path is not None:
            row.field_path = field_path
        await self._session.flush()
        return row

    async def set_status(self, definition_id: uuid.UUID, *, status: str, reviewer_identity: str) -> ValidationRuleDefinition:
        """Covers activate/reject/disable (kind="cel") and enable/disable
        (kind="toggle") — one status-transition method, same as
        TypeSuggestionRepository.resolve."""
        row = await self._session.get(ValidationRuleDefinition, definition_id)
        if row is None:
            raise ValueError(f"validation rule definition not found: {definition_id}")
        row.status = status
        row.reviewer_identity = reviewer_identity
        row.reviewed_at = datetime.now(UTC)
        await self._session.flush()
        return row


class ReferenceDataRepository:
    """Postgres-backed adapter of ``ReferenceDataPort`` (category d)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_employee_by_code(self, employee_code: str) -> dict | None:
        stmt = select(ReferenceEmployee).where(ReferenceEmployee.employee_code == employee_code)
        result = await self._session.execute(stmt)
        employee = result.scalar_one_or_none()
        if employee is None:
            return None
        return {"employee_code": employee.employee_code, "full_name": employee.full_name, "active": employee.active}

    async def list_active_employee_names(self) -> list[tuple[str, str]]:
        stmt = select(ReferenceEmployee).where(ReferenceEmployee.active.is_(True))
        result = await self._session.execute(stmt)
        return [(e.employee_code, e.full_name) for e in result.scalars().all()]


class SemanticCatalogRepository:
    """Backs api/routes/semantic_catalog.py and the pipeline's per-case
    semantic resolution. See persistence/models.py::SemanticCatalogVersion."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_seed(self) -> None:
        """Publish the in-code seed as version 1 if the table is empty —
        idempotent, called at API startup."""
        existing = await self._session.scalar(select(func.count()).select_from(SemanticCatalogVersion))
        if existing:
            return
        catalog = seed_catalog()
        self._session.add(
            SemanticCatalogVersion(
                version=1,
                status="published",
                definition=catalog.model_dump(mode="json"),
                content_hash=catalog.content_hash(),
                created_by="seed",
                published_by="seed",
                published_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def latest_published(self) -> SemanticCatalogVersion | None:
        stmt = (
            select(SemanticCatalogVersion)
            .where(SemanticCatalogVersion.status == "published")
            .order_by(SemanticCatalogVersion.version.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def load_active(self) -> tuple[SemanticCatalog, int] | None:
        row = await self.latest_published()
        if row is None:
            return None
        return SemanticCatalog.model_validate(row.definition), row.version

    async def get_version(self, version: int) -> SemanticCatalogVersion | None:
        return await self._session.scalar(select(SemanticCatalogVersion).where(SemanticCatalogVersion.version == version))

    async def list_versions(self) -> list[SemanticCatalogVersion]:
        result = await self._session.scalars(select(SemanticCatalogVersion).order_by(SemanticCatalogVersion.version.desc()))
        return list(result)

    async def create_draft(self, catalog: SemanticCatalog, *, created_by: str) -> SemanticCatalogVersion:
        current_max = await self._session.scalar(select(func.max(SemanticCatalogVersion.version)))
        row = SemanticCatalogVersion(
            version=(current_max or 0) + 1,
            status="draft",
            definition=catalog.model_dump(mode="json"),
            content_hash=catalog.content_hash(),
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def publish(self, row: SemanticCatalogVersion, *, published_by: str) -> SemanticCatalogVersion:
        row.status = "published"
        row.published_by = published_by
        row.published_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return row

