"""GET /validation — read-only, cross-document view over validation_issues.
Every issue already gets persisted there when a rule doesn't pass (see
pipeline/orchestrator.py); nothing exposed an aggregate view over HTTP
until now — same situation /audit was in before it got a route. Only
non-passing results are persisted (passing ones never reach the DB), so
this shows failures, not a full run log of every rule that executed."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session
from idp.persistence.repositories import ValidationRepository

router = APIRouter(prefix="/validation", tags=["validation"], dependencies=[Depends(get_current_user)])


class ValidationIssueResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID | None
    document_filename: str | None
    document_type: str | None
    batch_id: uuid.UUID
    rule_id: str
    category: str
    field_path: str | None
    severity: str
    message: str
    confidence: float
    confidence_method: str
    explanation: str
    created_at: datetime


class ValidationLogResponse(BaseModel):
    total: int
    issues: list[ValidationIssueResponse]


@router.get("", response_model=ValidationLogResponse)
async def list_validation_issues(
    category: str | None = None,
    severity: str | None = None,
    rule_id: str | None = None,
    document_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> ValidationLogResponse:
    repo = ValidationRepository(session)
    rows = await repo.list(category=category, severity=severity, rule_id=rule_id, document_type=document_type, limit=limit, offset=offset)
    total = await repo.count(category=category, severity=severity, rule_id=rule_id, document_type=document_type)
    return ValidationLogResponse(
        total=total,
        issues=[
            ValidationIssueResponse(
                id=row.id,
                document_id=row.document_id,
                document_filename=row.document.original_filename if row.document else None,
                document_type=row.document.document_type if row.document else None,
                batch_id=row.case_id,
                rule_id=row.rule_id,
                category=row.category,
                field_path=row.field_path,
                severity=row.severity,
                message=row.message,
                confidence=row.confidence,
                confidence_method=row.confidence_method,
                explanation=row.explanation,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )
