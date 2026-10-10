"""GET /review (pending queue), GET /review/reasons (the correction reason
codes) and POST /review/{id} (submit a correction — writes the full audit
trail: original value/confidence, reviewer identity, corrected value, the
coded reason and its justification (VRT-39), timestamp, model/prompt version).
A correction is written into the extraction and, when the value changed,
re-evaluates only the rules that read that field (VRT-40)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.case_service import dispatch_run, open_reprocess_run
from idp.api.routes.investigations import record_outcome
from idp.pipeline.investigation import ACTION_LABEL
from idp.api.deps import get_app_settings, get_current_user, get_db_session, require_role
from idp.config import Settings
from idp.domain.correction_reasons import CORRECTION_REASONS, REASONS_BY_CODE, CorrectionReason, ReasonCode
from idp.domain.document_type_catalog import DocumentTypeCatalog
from idp.domain.reprocess import ReprocessScope
from idp.domain.semantic import SemanticCatalog
from idp.persistence.models import Investigation, ReviewItem, User
from idp.persistence.repositories import CaseRepository, CaseRunRepository, DocumentRepository, DocumentTypeRepository, ReviewRepository, SemanticCatalogRepository
from idp.pipeline.case_evaluation import refresh_verdict
from idp.pipeline.orchestrator import extraction_schema
from idp.review.corrections import apply_correction
from idp.review.labels import describe_field

router = APIRouter(prefix="/review", tags=["review"], dependencies=[Depends(get_current_user)])


class Suggestion(BaseModel):
    investigation_id: uuid.UUID
    action: str
    action_label: str
    diagnosis: str
    value: Any
    confidence: float | None


class ReviewItemResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    field_path: str
    current_value: dict
    confidence: float
    reason: str
    status: str
    # What the reviewer reads instead of field_path (review/labels.py).
    label: str
    description: str | None
    attribute: str | None
    role: str | None
    document_type: str | None
    document_type_name: str | None
    filename: str
    case_id: uuid.UUID
    case_ref: str | None
    page: int | None
    source_text: str | None
    # The finding that sent a validation_issue item here.
    finding: str | None
    # What the discrepancy investigator suggests for this field (VRT-66), if it looked into it.
    suggestion: Suggestion | None = None



class ReviewCorrectionRequest(BaseModel):
    corrected_value: Any
    reason_code: ReasonCode = Field(description="Por qué se corrige (GET /review/reasons).")
    justification: str | None = Field(default=None, description="Sustento en palabras del revisor; obligatorio para algunos motivos.")
    model_version: str | None = None
    prompt_version: str | None = None

    @model_validator(mode="after")
    def _justified(self) -> ReviewCorrectionRequest:
        reason = REASONS_BY_CODE[self.reason_code]
        if reason.requires_justification and len((self.justification or "").strip()) < 5:
            raise ValueError(f"el motivo '{reason.label}' requiere un sustento")
        return self


class ReviewCorrectionResponse(BaseModel):
    review_item_id: uuid.UUID
    status: str
    # The case run that re-evaluates the rules reading the field, when the
    # value changed and no other run was in progress.
    run_number: int | None = None


@router.get("", response_model=list[ReviewItemResponse])
async def list_pending_review(session: AsyncSession = Depends(get_db_session)) -> list[ReviewItemResponse]:
    items = await ReviewRepository(session).list_pending()
    type_catalog = await DocumentTypeRepository(session).load_catalog()
    loaded = await SemanticCatalogRepository(session).load_active()
    semantic = loaded[0] if loaded is not None else None
    suggestions = await _suggestions(session, [i.document_id for i in items])
    return [_describe(item, type_catalog, semantic).model_copy(update={"suggestion": suggestions.get((item.document_id, item.field_path))}) for item in items]


async def _suggestions(session: AsyncSession, document_ids: list[uuid.UUID]) -> dict[tuple[uuid.UUID, str], Suggestion]:
    """The latest pending suggestion of the investigator per (document, field)."""
    rows = (
        await session.scalars(
            select(Investigation)
            .where(Investigation.document_id.in_(document_ids), Investigation.status == "done", Investigation.outcome == "pending")
            .order_by(Investigation.finished_at.desc())
        )
    ).all()
    out: dict[tuple[uuid.UUID, str], Suggestion] = {}
    for r in rows:
        if r.document_id is not None and r.field_path is not None and r.action is not None:
            out.setdefault(
                (r.document_id, r.field_path),
                Suggestion(
                    investigation_id=r.id, action=r.action, action_label=ACTION_LABEL.get(r.action, r.action), diagnosis=r.diagnosis or "",
                    value=r.suggested_value, confidence=r.confidence,
                ),
            )
    return out


def _describe(item: ReviewItem, type_catalog: DocumentTypeCatalog, semantic: SemanticCatalog | None) -> ReviewItemResponse:
    document = item.document
    extraction = document.extraction
    definition = None
    if document.document_type is not None and extraction is not None:
        version = 1 if extraction.schema_version == "1.0" else int(extraction.schema_version)
        definition = type_catalog.definition(document.document_type, version)
    field = describe_field(
        item.field_path,
        document_type=document.document_type,
        definition=definition,
        catalog=semantic,
        payload=extraction.payload if extraction is not None else None,
    )
    leaf = _leaf(extraction.payload if extraction is not None else None, item.field_path)
    finding = next(
        (i.message for i in document.active_validation_issues if i.field_path == item.field_path and i.severity in ("warning", "error")),
        None,
    )
    return ReviewItemResponse(
        id=item.id,
        document_id=item.document_id,
        field_path=item.field_path,
        current_value=item.current_value,
        confidence=item.confidence,
        reason=item.reason,
        status=item.status,
        label=field.label,
        description=field.description,
        attribute=field.attribute,
        role=field.role,
        document_type=document.document_type,
        document_type_name=definition.display_name if definition is not None else None,
        filename=document.original_filename,
        case_id=document.case_id,
        case_ref=document.case.external_ref,
        page=leaf.get("page"),
        source_text=leaf.get("source_text"),
        finding=finding if item.reason == "validation_issue" else None,
    )


def _leaf(payload: dict | None, field_path: str) -> dict:
    """The stored Extracted[T] envelope at ``field_path`` ({} if absent)."""
    node: Any = payload
    for part in re.split(r"\.|\[(\d+)\]", field_path):
        if not part:
            continue
        if isinstance(node, list) and part.isdigit():
            node = node[int(part)] if int(part) < len(node) else None
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return {}
    return node if isinstance(node, dict) else {}


@router.get("/reasons", response_model=list[CorrectionReason])
async def correction_reasons() -> list[CorrectionReason]:
    return CORRECTION_REASONS


@router.post("/{review_item_id}", response_model=ReviewCorrectionResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def submit_correction(
    review_item_id: uuid.UUID,
    body: ReviewCorrectionRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> ReviewCorrectionResponse:
    repo = ReviewRepository(session)
    item = await repo.get(review_item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review item not found")
    document_repo = DocumentRepository(session)
    document = await document_repo.get(item.document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")

    extraction, written = document.extraction, False
    if body.corrected_value != (item.current_value or {}).get("value") and extraction is not None and document.document_type is not None:
        type_catalog = await DocumentTypeRepository(session).load_catalog()
        schema = extraction_schema(type_catalog, document.document_type, extraction.schema_version)
        try:
            extraction.payload = apply_correction(extraction.payload, item.field_path, body.corrected_value, schema)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        written = True

    await repo.resolve(
        review_item_id,
        reviewer_identity=current_user.name,
        corrected_value={"value": body.corrected_value},
        reason_code=body.reason_code,
        justification=(body.justification or "").strip() or None,
        model_version=body.model_version,
        prompt_version=body.prompt_version,
    )
    # Did the reviewer take the investigator's suggestion for this field? (VRT-66)
    await record_outcome(session, document_id=document.id, field_path=item.field_path, corrected_value=body.corrected_value, reason_code=body.reason_code)
    # The case verdict depends on pending reviews (VRT-27): once a
    # document has none left it is done, and the verdict is recomputed.
    if not await repo.has_pending_for_document(document.id):
        await document_repo.set_status(document.id, "completed")
    await refresh_verdict(session, document.case_id)

    run, case = None, None
    if written and not await CaseRunRepository(session).has_active_run(document.case_id):
        case = await CaseRepository(session).get(document.case_id)
    if case is not None:
        scope = ReprocessScope(kind="attribute", document_id=document.id, field_path=item.field_path)
        run = await open_reprocess_run(session, settings, case, scope, trigger="correction")
    await session.commit()
    if run is not None and case is not None:
        try:
            await dispatch_run(session, settings, case, run, background_tasks)
        except HTTPException:
            run = None  # the correction stands; dispatch_run marked the run failed
    return ReviewCorrectionResponse(review_item_id=review_item_id, status="resolved", run_number=run.run_number if run else None)

