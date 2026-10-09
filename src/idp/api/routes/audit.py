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

from idp.api.deps import get_current_user, get_db_session
from idp.domain.correction_reasons import REASONS_BY_CODE
from idp.persistence.repositories import ReviewRepository

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(get_current_user)])


class AuditEntryResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    field_path: str
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
) -> AuditLogResponse:
    repo = ReviewRepository(session)
    rows = await repo.list_audit_entries(limit=limit, offset=offset)
    total = await repo.count_audit_entries()
    return AuditLogResponse(
        total=total,
        entries=[
            AuditEntryResponse(
                id=row.id,
                document_id=row.review_item.document_id,
                field_path=row.review_item.field_path,
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
            )
            for row in rows
        ],
    )


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
            reason_label=REASONS_BY_CODE[code].label if code in REASONS_BY_CODE else "Sin motivo (anterior a VRT-39)",
            document_type=document_type,
            count=count,
        )
        for code, document_type, count in await ReviewRepository(session).correction_summary()
    ]

