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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, get_principal
from idp.api.disclosure import CaseMaskers
from idp.auth.authenticate import Principal
from idp.api.routes.review import field_label
from idp.persistence.models import Case
from idp.persistence.repositories import DocumentTypeRepository, SemanticCatalogRepository, ValidationRepository

router = APIRouter(prefix="/validation", tags=["validation"], dependencies=[Depends(get_current_user)])


class ValidationIssueResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID | None
    document_filename: str | None
    document_type: str | None
    batch_id: uuid.UUID
    case_ref: str | None = None  # the case's name for a person (VRT-104)
    rule_id: str
    category: str
    field_path: str | None
    field_label: str | None = None  # the field said for a person (review/labels.py)
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
    principal: Principal = Depends(get_principal),
) -> ValidationLogResponse:
    repo = ValidationRepository(session)
    rows = await repo.list(category=category, severity=severity, rule_id=rule_id, document_type=document_type, limit=limit, offset=offset)
    total = await repo.count(category=category, severity=severity, rule_id=rule_id, document_type=document_type)
    maskers = CaseMaskers(session, principal)  # findings quote the case's data (VRT-58)
    type_catalog = await DocumentTypeRepository(session).load_catalog()
    loaded = await SemanticCatalogRepository(session).load_active()
    semantic = loaded[0] if loaded is not None else None
    refs = dict((await session.execute(select(Case.id, Case.external_ref).where(Case.id.in_({r.case_id for r in rows})))).tuples().all())
    issues = []
    for row in rows:
        issue = ValidationIssueResponse(
            id=row.id,
            document_id=row.document_id,
            document_filename=row.document.original_filename if row.document else None,
            document_type=row.document.document_type if row.document else None,
            batch_id=row.case_id,
            case_ref=refs.get(row.case_id),
            rule_id=row.rule_id,
            category=row.category,
            field_path=row.field_path,
            field_label=field_label(row.document, row.field_path, type_catalog, semantic).label if row.document and row.field_path else None,
            severity=row.severity,
            message=row.message,
            confidence=row.confidence,
            confidence_method=row.confidence_method,
            explanation=row.explanation,
            created_at=row.created_at,
        )
        issues.append(ValidationIssueResponse.model_validate((await maskers(row.case_id)).json(issue.model_dump(mode="json"))))
    return ValidationLogResponse(total=total, issues=issues)
