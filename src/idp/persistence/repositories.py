"""Repository pattern: the only layer allowed to build SQLAlchemy queries.
Domain/service code depends on these, never on ``models.py`` + raw queries
directly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Text, func, or_, select, update
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from idp.domain.process_profile import ProcessProfileDefinition
from idp.domain.process_profile_seed import SEED_PROFILES
from idp.domain.semantic import SemanticCatalog
from idp.domain.semantic_seed import seed_catalog
from idp.persistence.models import (
    AuditLogEntry,
    Case,
    CaseCondition,
    CaseRun,
    Document,
    DocumentTypeSuggestion,
    Extraction,
    OutboxEvent,
    ProcessProfile,
    ProcessProfileVersion,
    ReferenceEmployee,
    ReviewItem,
    SemanticCatalogVersion,
    User,
    ValidationIssue,
    ValidationRuleDefinition,
    WebhookDelivery,
    WebhookEndpoint,
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


class CaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant: str = "default",
        request_input_payload: dict | None = None,
        profile_version_id: uuid.UUID | None = None,
        external_ref: str | None = None,
        channel: str = "backoffice",
        idempotency_key: str | None = None,
        idempotency_fingerprint: str | None = None,
    ) -> Case:
        case = Case(
            tenant=tenant,
            request_input_payload=request_input_payload,
            profile_version_id=profile_version_id,
            external_ref=external_ref,
            channel=channel,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=idempotency_fingerprint,
        )
        self._session.add(case)
        await self._session.flush()
        return case

    async def get(self, case_id: uuid.UUID) -> Case | None:
        # populate_existing=True — see DocumentRepository.get() for why this
        # is required, not optional: without it, polling GET /batches/{id}
        # within the same session as an in-flight pipeline run can return
        # stale (pre-extraction) document/relationship state.
        stmt = (
            select(Case)
            .where(Case.id == case_id)
            .options(
                selectinload(Case.documents).selectinload(Document.extraction),
                selectinload(Case.documents).selectinload(Document.active_validation_issues),
                selectinload(Case.runs),
                selectinload(Case.profile_version).selectinload(ProcessProfileVersion.profile),
            )
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, *, tenant: str, idempotency_key: str) -> Case | None:
        stmt = select(Case.id).where(Case.tenant == tenant, Case.idempotency_key == idempotency_key)
        case_id = await self._session.scalar(stmt)
        return await self.get(case_id) if case_id is not None else None

    async def list(self, *, external_ref: str | None = None, limit: int = 50, offset: int = 0) -> list[Case]:
        stmt = select(Case).options(selectinload(Case.profile_version).selectinload(ProcessProfileVersion.profile))
        if external_ref is not None:
            stmt = stmt.where(Case.external_ref == external_ref)
        stmt = stmt.order_by(Case.created_at.desc()).limit(limit).offset(offset)
        return list((await self._session.scalars(stmt)).all())

    async def set_status(self, case_id: uuid.UUID, status: str) -> None:
        case = await self._session.get(Case, case_id)
        if case is not None:
            case.status = status


class CaseRunRepository:
    """Each evaluation of a case (VRT-25). See persistence/models.py::CaseRun."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_next(self, case: Case, *, trigger: str) -> CaseRun:
        current_max = await self._session.scalar(select(func.max(CaseRun.run_number)).where(CaseRun.case_id == case.id))
        run = CaseRun(case_id=case.id, run_number=(current_max or 0) + 1, trigger=trigger, profile_version_id=case.profile_version_id)
        self._session.add(run)
        await self._session.flush()
        return run

    async def get(self, run_id: uuid.UUID) -> CaseRun | None:
        return await self._session.get(CaseRun, run_id)

    async def has_active_run(self, case_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(CaseRun).where(CaseRun.case_id == case_id, CaseRun.status.in_(("pending", "running")))
        return bool(await self._session.scalar(stmt))

    async def list_unfinished_with_ref(self) -> list[CaseRun]:
        """Runs handed to an executor that have not finished — what the
        worker's reconciler checks against aeon (VRT-26)."""
        stmt = select(CaseRun).where(CaseRun.status.in_(("pending", "running")), CaseRun.execution_ref.is_not(None))
        return list((await self._session.scalars(stmt)).all())

    async def mark_running(self, run: CaseRun, *, provenance: dict) -> None:
        run.status, run.provenance, run.started_at = "running", provenance, datetime.now(UTC)

    async def mark_finished(self, run: CaseRun, *, status: str, error: str | None = None) -> None:
        run.status, run.error, run.finished_at = status, error, datetime.now(UTC)


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, case_id: uuid.UUID, storage_key: str, original_filename: str) -> Document:
        doc = Document(case_id=case_id, storage_key=storage_key, original_filename=original_filename)
        self._session.add(doc)
        await self._session.flush()
        return doc

    async def create_child(
        self, *, case_id: uuid.UUID, parent_document_id: uuid.UUID, storage_key: str, original_filename: str, page_start: int, page_end: int
    ) -> Document:
        """One logical document spawned by segmentation from a physical
        upload that bundled more than one — same storage_key as the parent
        (no re-upload needed, it's the same file), scoped to its page range."""
        doc = Document(
            case_id=case_id,
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
                selectinload(Document.active_validation_issues),
                selectinload(Document.review_items),
            )
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_child(self, parent_document_id: uuid.UUID, *, page_start: int, page_end: int) -> Document | None:
        """The segment child for this page range, if an earlier attempt
        already created it."""
        stmt = (
            select(Document)
            .where(Document.parent_document_id == parent_document_id, Document.page_start == page_start, Document.page_end == page_end)
            .options(selectinload(Document.extraction))
            .execution_options(populate_existing=True)
        )
        return await self._session.scalar(stmt)

    async def list_for_case(self, case_id: uuid.UUID) -> list[Document]:
        # populate_existing=True: within a case run, these Document objects
        # are already in the session's identity map from before extraction
        # (extraction=None); without it the freshly saved extractions are
        # not seen and validation silently skips every document.
        stmt = (
            select(Document)
            .where(Document.case_id == case_id)
            .options(selectinload(Document.extraction))
            .execution_options(populate_existing=True)
        )
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

    async def list_for_case(self, case_id: uuid.UUID) -> list[ValidationIssue]:
        """The case's current issues — those of its latest evaluation."""
        stmt = select(ValidationIssue).where(ValidationIssue.case_id == case_id, ValidationIssue.superseded_at.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def supersede_active(self, case_id: uuid.UUID) -> int:
        """A new run re-evaluates the whole case: the previous run's issues
        stay for audit but stop counting as current."""
        result = await self._session.execute(
            update(ValidationIssue)
            .where(ValidationIssue.case_id == case_id, ValidationIssue.superseded_at.is_(None))
            .values(superseded_at=datetime.now(UTC))
        )
        return result.rowcount or 0  # type: ignore[attr-defined]

    @staticmethod
    def _filtered(stmt, *, category: str | None, severity: str | None, rule_id: str | None, document_type: str | None):
        stmt = stmt.where(ValidationIssue.superseded_at.is_(None))
        if category is not None:
            stmt = stmt.where(ValidationIssue.category == category)
        if severity is not None:
            stmt = stmt.where(ValidationIssue.severity == severity)
        if rule_id is not None:
            stmt = stmt.where(ValidationIssue.rule_id == rule_id)
        if document_type is not None:
            # Only ValidationIssue rows tied to a real document can match a
            # document_type filter — no rows here are case-only today, but
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

    async def has_item_for_field(self, document_id: uuid.UUID, field_path: str) -> bool:
        """True if this field was already sent to review (pending or
        resolved). A re-evaluation of the case must not ask a human twice
        about the same field — applying a correction and re-validating is
        VRT-40."""
        stmt = select(func.count()).select_from(ReviewItem).where(ReviewItem.document_id == document_id, ReviewItem.field_path == field_path)
        return bool(await self._session.scalar(stmt))

    async def has_pending_for_document(self, document_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(ReviewItem).where(ReviewItem.document_id == document_id, ReviewItem.status == "pending")
        return bool(await self._session.scalar(stmt))

    async def pending_document_ids_for_case(self, case_id: uuid.UUID) -> set[uuid.UUID]:
        stmt = (
            select(ReviewItem.document_id)
            .join(Document, Document.id == ReviewItem.document_id)
            .where(Document.case_id == case_id, ReviewItem.status == "pending")
            .distinct()
        )
        return set((await self._session.scalars(stmt)).all())

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
        case_id: uuid.UUID,
        suggested_type_name: str,
        suggested_display_name: str,
        rationale: str,
        fields: list[dict],
    ) -> DocumentTypeSuggestion:
        row = DocumentTypeSuggestion(
            document_id=document_id,
            case_id=case_id,
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


class ProcessProfileRepository:
    """Backs api/routes/profiles.py and, from VRT-25 on, case creation. See
    persistence/models.py::ProcessProfile / ProcessProfileVersion."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_seed(self) -> None:
        """Publish the seed profiles as version 1 if there are none —
        idempotent, called at API startup after the semantic catalog seed."""
        if await self._session.scalar(select(func.count()).select_from(ProcessProfile)):
            return
        now = datetime.now(UTC)
        for key, name, description, build in SEED_PROFILES:
            definition = build()
            profile = ProcessProfile(key=key, name=name, description=description)
            profile.versions.append(
                ProcessProfileVersion(
                    version=1,
                    status="published",
                    definition=definition.model_dump(mode="json"),
                    content_hash=definition.content_hash(),
                    semantic_catalog_version=definition.semantic_catalog_version,
                    created_by="seed",
                    published_by="seed",
                    published_at=now,
                )
            )
            self._session.add(profile)
        await self._session.commit()

    async def list_profiles(self) -> list[ProcessProfile]:
        stmt = select(ProcessProfile).options(selectinload(ProcessProfile.versions)).order_by(ProcessProfile.key)
        return list((await self._session.scalars(stmt)).all())

    async def get_by_key(self, key: str) -> ProcessProfile | None:
        stmt = select(ProcessProfile).where(ProcessProfile.key == key).options(selectinload(ProcessProfile.versions))
        return await self._session.scalar(stmt)

    async def create_profile(self, *, key: str, name: str, description: str | None) -> ProcessProfile:
        profile = ProcessProfile(key=key, name=name, description=description)
        self._session.add(profile)
        await self._session.commit()
        return await self.get_by_key(key)  # type: ignore[return-value]

    async def get_version(self, profile: ProcessProfile, version: int) -> ProcessProfileVersion | None:
        return next((v for v in profile.versions if v.version == version), None)

    @staticmethod
    def latest_published(profile: ProcessProfile) -> ProcessProfileVersion | None:
        published = [v for v in profile.versions if v.status == "published"]
        return max(published, key=lambda v: v.version) if published else None

    async def create_draft(self, profile: ProcessProfile, definition: ProcessProfileDefinition, *, created_by: str) -> ProcessProfileVersion:
        row = ProcessProfileVersion(
            profile_id=profile.id,
            version=max((v.version for v in profile.versions), default=0) + 1,
            status="draft",
            definition=definition.model_dump(mode="json"),
            content_hash=definition.content_hash(),
            semantic_catalog_version=definition.semantic_catalog_version,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def set_status(self, row: ProcessProfileVersion, *, status: str, actor: str) -> ProcessProfileVersion:
        row.status = status
        if status == "published":
            row.published_by, row.published_at = actor, datetime.now(UTC)
        elif status == "retired":
            row.retired_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return row


class CaseConditionRepository:
    """Missing documents/evidence of a case (VRT-27). See
    persistence/models.py::CaseCondition."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_case(self, case_id: uuid.UUID) -> list[CaseCondition]:
        stmt = select(CaseCondition).where(CaseCondition.case_id == case_id).order_by(CaseCondition.opened_at)
        return list((await self._session.scalars(stmt)).all())

    async def get(self, condition_id: uuid.UUID) -> CaseCondition | None:
        return await self._session.get(CaseCondition, condition_id)

    async def latest_by_key(self, case_id: uuid.UUID) -> dict[str, CaseCondition]:
        """The most recent condition per checklist key: the one a run
        updates instead of opening a duplicate."""
        latest: dict[str, CaseCondition] = {}
        for condition in await self.list_for_case(case_id):
            latest[condition.key] = condition
        return latest

    async def add(self, condition: CaseCondition) -> CaseCondition:
        self._session.add(condition)
        await self._session.flush()
        return condition

    async def resolve(self, condition: CaseCondition, *, run_id: uuid.UUID | None, document_id: uuid.UUID | None, note: str) -> None:
        condition.status, condition.resolved_in_run_id, condition.resolved_by_document_id = "resolved", run_id, document_id
        condition.note, condition.resolved_at = note, datetime.now(UTC)

    async def waive(self, condition: CaseCondition, *, by: str, reason: str) -> None:
        condition.status, condition.waived_by, condition.waived_reason, condition.resolved_at = "waived", by, reason, datetime.now(UTC)


class OutboxRepository:
    """Domain events waiting to be fanned out into webhook deliveries
    (VRT-28). Claims use SKIP LOCKED so several dispatchers can run."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_undispatched(self, limit: int = 100, *, tenant: str | None = None) -> list[OutboxEvent]:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.dispatched_at.is_(None), *([OutboxEvent.tenant == tenant] if tenant is not None else []))
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_recent(self, *, subject: str | None = None, limit: int = 50) -> list[OutboxEvent]:
        stmt = select(OutboxEvent).order_by(OutboxEvent.created_at.desc()).limit(limit)
        if subject is not None:
            stmt = stmt.where(OutboxEvent.subject == subject)
        return list((await self._session.scalars(stmt)).all())


class WebhookEndpointRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, endpoint: WebhookEndpoint) -> WebhookEndpoint:
        self._session.add(endpoint)
        await self._session.flush()
        return endpoint

    async def get(self, endpoint_id: uuid.UUID) -> WebhookEndpoint | None:
        return await self._session.get(WebhookEndpoint, endpoint_id)

    async def list(self, *, tenant: str) -> list[WebhookEndpoint]:
        stmt = select(WebhookEndpoint).where(WebhookEndpoint.tenant == tenant).order_by(WebhookEndpoint.created_at)
        return list((await self._session.scalars(stmt)).all())

    async def subscribed(self, *, tenant: str, event_type: str) -> list[WebhookEndpoint]:
        """Active endpoints of the tenant that want this type ([] = all)."""
        stmt = select(WebhookEndpoint).where(WebhookEndpoint.tenant == tenant, WebhookEndpoint.active.is_(True))
        return [e for e in (await self._session.scalars(stmt)).all() if not e.event_types or event_type in e.event_types]

    async def disable(self, endpoint: WebhookEndpoint) -> None:
        endpoint.active, endpoint.disabled_at = False, datetime.now(UTC)


class WebhookDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_for(self, event_id: uuid.UUID, endpoint_ids: list[uuid.UUID]) -> None:
        """One delivery per endpoint; idempotent (a re-run of the fan-out
        never duplicates)."""
        if not endpoint_ids:
            return
        stmt = pg_insert(WebhookDelivery).values([{"id": uuid.uuid4(), "event_id": event_id, "endpoint_id": e} for e in endpoint_ids])
        await self._session.execute(stmt.on_conflict_do_nothing(index_elements=["event_id", "endpoint_id"]))

    async def claim_due(self, *, now: datetime, lease_until: datetime, limit: int = 50, tenant: str | None = None) -> list[WebhookDelivery]:
        """Due pending deliveries, leased (next_attempt_at pushed to
        ``lease_until``) so a crashed dispatcher's work is retried by
        another once the lease expires — at-least-once."""
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= now)
            .where(*([WebhookDelivery.endpoint_id.in_(select(WebhookEndpoint.id).where(WebhookEndpoint.tenant == tenant))] if tenant is not None else []))
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .options(selectinload(WebhookDelivery.event), selectinload(WebhookDelivery.endpoint))
        )
        rows = list((await self._session.scalars(stmt)).all())
        for row in rows:
            row.next_attempt_at = lease_until
        return rows

    async def list_for_endpoint(self, endpoint_id: uuid.UUID, *, limit: int = 50) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.endpoint_id == endpoint_id)
            .options(selectinload(WebhookDelivery.event))
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.scalars(stmt)).all())

