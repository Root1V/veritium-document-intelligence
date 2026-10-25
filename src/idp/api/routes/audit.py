"""GET /audit — read-only correction history: every field a human ever
corrected via POST /review/{id}, who corrected it, and the before/after
value. `audit_log` has been populated since Phase 0 (a first-class
deliverable per its own model docstring), but nothing exposed it over HTTP
until now — this route only surfaces data that already existed.

GET /audit/correction-summary — why corrections happen: counts by coded
reason and document type (VRT-39)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, get_principal
from idp.api.disclosure import CaseMaskers
from idp.auth.authenticate import Principal
from idp.domain.correction_reasons import REASONS_BY_CODE
from idp.api.routes.review import field_label
from idp.persistence.repositories import DocumentTypeRepository, ReviewRepository, SemanticCatalogRepository

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(get_current_user)])


class AuditEntryResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_filename: str | None = None
    field_path: str
    field_label: str | None = None  # the field said for a person (review/labels.py)
    reviewer_identity: str
    original_value: dict
    corrected_value: dict
    reason_code: str | None
    reason_label: str | None
    justification: str | None
    original_confidence: float
    model_version: str | None
    prompt_version: str | None
    timestamp: datetime


class AuditLogResponse(BaseModel):
    total: int
    entries: list[AuditEntryResponse]


@router.get("", response_model=AuditLogResponse)
async def list_audit_log(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(get_principal),
) -> AuditLogResponse:
    repo = ReviewRepository(session)
    rows = await repo.list_audit_entries(limit=limit, offset=offset)
    total = await repo.count_audit_entries()
    maskers = CaseMaskers(session, principal)
    type_catalog = await DocumentTypeRepository(session).load_catalog()
    loaded = await SemanticCatalogRepository(session).load_active()
    semantic = loaded[0] if loaded is not None else None
    entries = []
    for row in rows:
        document, path = row.review_item.document, row.review_item.field_path
        # Both values are that field's; the one a correction replaced is no longer in the document (VRT-58).
        masker = await maskers(document.case_id, (document.document_type, {path: row.original_value}), (document.document_type, {path: row.corrected_value}))
        entries.append(AuditEntryResponse.model_validate(masker.json(
            AuditEntryResponse(
                id=row.id,
                document_id=row.review_item.document_id,
                document_filename=document.original_filename,
                field_path=row.review_item.field_path,
                field_label=field_label(document, path, type_catalog, semantic).label,
                reviewer_identity=row.reviewer_identity,
                original_value=row.original_value,
                corrected_value=row.corrected_value,
                reason_code=row.reason_code,
                reason_label=REASONS_BY_CODE[row.reason_code].label if row.reason_code in REASONS_BY_CODE else None,
                justification=row.justification,
                original_confidence=row.original_confidence,
                model_version=row.model_version,
                prompt_version=row.prompt_version,
                timestamp=row.timestamp,
            ).model_dump(mode="json")
        )))
    return AuditLogResponse(total=total, entries=entries)


class CorrectionSummaryRow(BaseModel):
    reason_code: str | None
    reason_label: str
    document_type: str | None
    count: int


@router.get("/correction-summary", response_model=list[CorrectionSummaryRow])
async def correction_summary(session: AsyncSession = Depends(get_db_session)) -> list[CorrectionSummaryRow]:
    return [
        CorrectionSummaryRow(
            reason_code=code,
            reason_label=REASONS_BY_CODE[code].label if code in REASONS_BY_CODE else "Sin motivo registrado",
            document_type=document_type,
            count=count,
        )
        for code, document_type, count in await ReviewRepository(session).correction_summary()
    ]

