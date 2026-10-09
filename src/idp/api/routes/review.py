"""GET /review (pending queue), GET /review/reasons (the correction reason
codes) and POST /review/{id} (submit a correction — writes the full audit
trail: original value/confidence, reviewer identity, corrected value, the
coded reason and its justification (VRT-39), timestamp, model/prompt version)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, require_role
from idp.domain.correction_reasons import CORRECTION_REASONS, REASONS_BY_CODE, CorrectionReason, ReasonCode
from idp.domain.document_type_catalog import DocumentTypeCatalog
from idp.domain.semantic import SemanticCatalog
from idp.persistence.models import ReviewItem, User
from idp.persistence.repositories import DocumentRepository, DocumentTypeRepository, ReviewRepository, SemanticCatalogRepository
from idp.pipeline.case_evaluation import refresh_verdict
from idp.review.labels import describe_field

router = APIRouter(prefix="/review", tags=["review"], dependencies=[Depends(get_current_user)])


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


@router.get("", response_model=list[ReviewItemResponse])
async def list_pending_review(session: AsyncSession = Depends(get_db_session)) -> list[ReviewItemResponse]:
    items = await ReviewRepository(session).list_pending()
    type_catalog = await DocumentTypeRepository(session).load_catalog()
    loaded = await SemanticCatalogRepository(session).load_active()
    semantic = loaded[0] if loaded is not None else None
    return [_describe(item, type_catalog, semantic) for item in items]


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
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ReviewCorrectionResponse:
    repo = ReviewRepository(session)
    item = await repo.get(review_item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review item not found")

    await repo.resolve(
        review_item_id,
        reviewer_identity=current_user.name,
        corrected_value={"value": body.corrected_value},
        reason_code=body.reason_code,
        justification=(body.justification or "").strip() or None,
        model_version=body.model_version,
        prompt_version=body.prompt_version,
    )
    # The case verdict depends on pending reviews (VRT-27): once a
    # document has none left it is done, and the verdict is recomputed.
    document_repo = DocumentRepository(session)
    document = await document_repo.get(item.document_id)
    if document is not None:
        if not await repo.has_pending_for_document(document.id):
            await document_repo.set_status(document.id, "completed")
        await refresh_verdict(session, document.case_id)
    await session.commit()
    return ReviewCorrectionResponse(review_item_id=review_item_id, status="resolved")
