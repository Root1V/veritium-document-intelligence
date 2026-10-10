"""Investigations of findings (VRT-66).

POST /v1/cases/{id}/investigations        investigate the case's findings (or one: ``validation_issue_id``) — 202
GET  /v1/cases/{id}/investigations        the latest investigation of each finding
POST /v1/investigations/{id}/dismiss      the reviewer discards the suggestion
GET  /v1/investigations/stats             how the suggestions fared: accepted, corrected otherwise, dismissed

On demand: each investigation costs model calls. A correction of the
suggested field records on its own whether the suggestion was accepted."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_current_user, get_db_session, require_role
from idp.config import Settings
from idp.persistence.models import Investigation, User, ValidationIssue
from idp.persistence.repositories import CaseRepository
from idp.pipeline.investigation import ACTION_LABEL, CAUSE_LABEL, launch

router = APIRouter(prefix="/v1", tags=["investigations"], dependencies=[Depends(get_current_user)])

_INVESTIGATORS = ("operador", "admin", "especialista_ia")


class InvestigationRequest(BaseModel):
    validation_issue_id: uuid.UUID | None = None


class InvestigationView(BaseModel):
    id: uuid.UUID
    validation_issue_id: uuid.UUID | None
    rule_id: str
    finding: str
    status: str
    diagnosis: str | None
    cause: str | None
    cause_label: str | None
    action: str | None
    action_label: str | None
    document_id: uuid.UUID | None
    field_path: str | None
    suggested_value: Any
    confidence: float | None
    evidence: list[dict[str, Any]]
    tools_used: list[str]
    outcome: str
    error: str | None
    created_by: str
    created_at: datetime
    finished_at: datetime | None


class InvestigationStats(BaseModel):
    investigated: int
    with_correction: int
    accepted: int
    overridden: int
    dismissed: int
    pending: int
    acceptance_rate: float | None  # of the suggested corrections a reviewer already resolved
    by_cause: dict[str, int]


def view(row: Investigation) -> InvestigationView:
    return InvestigationView(
        id=row.id, validation_issue_id=row.validation_issue_id, rule_id=row.rule_id, finding=row.finding, status=row.status, diagnosis=row.diagnosis,
        cause=row.cause, cause_label=CAUSE_LABEL.get(row.cause or ""), action=row.action, action_label=ACTION_LABEL.get(row.action or ""),
        document_id=row.document_id, field_path=row.field_path, suggested_value=row.suggested_value, confidence=row.confidence, evidence=row.evidence or [],
        tools_used=[t["tool"] for t in row.trace or []], outcome=row.outcome, error=row.error, created_by=row.created_by, created_at=row.created_at,
        finished_at=row.finished_at,
    )


@router.post("/cases/{case_id}/investigations", response_model=list[InvestigationView], status_code=status.HTTP_202_ACCEPTED)
async def investigate_case(
    case_id: uuid.UUID,
    body: InvestigationRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(require_role(*_INVESTIGATORS)),
) -> list[InvestigationView]:
    case = await CaseRepository(session).get(case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    stmt = select(ValidationIssue).where(
        ValidationIssue.case_id == case_id, ValidationIssue.superseded_at.is_(None), ValidationIssue.severity.in_(("warning", "error"))
    )
    if body is not None and body.validation_issue_id is not None:
        stmt = stmt.where(ValidationIssue.id == body.validation_issue_id)
    issues = list((await session.scalars(stmt.order_by(ValidationIssue.created_at))).all())
    if not issues:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no hay hallazgos vigentes que investigar")
    running = set(
        (
            await session.scalars(
                select(Investigation.validation_issue_id).where(Investigation.case_id == case_id, Investigation.status == "running")
            )
        ).all()
    )
    rows = [
        Investigation(case_id=case_id, validation_issue_id=i.id, rule_id=i.rule_id, finding=i.message, created_by=user.name)
        for i in issues
        if i.id not in running
    ]
    session.add_all(rows)
    await session.commit()
    launch(settings, [r.id for r in rows])
    return [view(r) for r in rows]


@router.get("/cases/{case_id}/investigations", response_model=list[InvestigationView])
async def case_investigations(case_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> list[InvestigationView]:
    rows = (await session.scalars(select(Investigation).where(Investigation.case_id == case_id).order_by(Investigation.created_at.desc()))).all()
    latest: dict[Any, Investigation] = {}
    for r in rows:
        latest.setdefault(r.validation_issue_id or r.id, r)
    return [view(r) for r in latest.values()]


@router.post("/investigations/{investigation_id}/dismiss", response_model=InvestigationView, dependencies=[Depends(require_role("operador", "admin"))])
async def dismiss(investigation_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> InvestigationView:
    row = await session.get(Investigation, investigation_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="investigation not found")
    if row.outcome == "pending":
        row.outcome, row.resolved_at = "dismissed", datetime.now(UTC)
        await session.commit()
    return view(row)


@router.get("/investigations/stats", response_model=InvestigationStats)
async def stats(session: AsyncSession = Depends(get_db_session)) -> InvestigationStats:
    done = select(Investigation).where(Investigation.status == "done").subquery()
    outcomes: dict[str, int] = {o: n for o, n in (await session.execute(select(done.c.outcome, func.count()).group_by(done.c.outcome))).tuples()}
    corrections: dict[str, int] = {
        o: n for o, n in (await session.execute(select(done.c.outcome, func.count()).where(done.c.action == "corregir_dato").group_by(done.c.outcome))).tuples()
    }
    causes: dict[str | None, int] = {c: n for c, n in (await session.execute(select(done.c.cause, func.count()).group_by(done.c.cause))).tuples()}
    resolved = corrections.get("accepted", 0) + corrections.get("overridden", 0) + corrections.get("dismissed", 0)
    return InvestigationStats(
        investigated=sum(outcomes.values()), with_correction=sum(corrections.values()), accepted=outcomes.get("accepted", 0),
        overridden=outcomes.get("overridden", 0), dismissed=outcomes.get("dismissed", 0), pending=outcomes.get("pending", 0),
        acceptance_rate=corrections.get("accepted", 0) / resolved if resolved else None,
        by_cause={CAUSE_LABEL.get(k or "", k or "?"): v for k, v in causes.items()},
    )


async def record_outcome(session: AsyncSession, *, document_id: uuid.UUID, field_path: str, corrected_value: Any, reason_code: str) -> None:
    """A correction of a field an investigation pointed at says whether the
    reviewer took the suggestion — called by the review queue: the same
    value it suggested, or keeping it as it was when it suggested confirming."""
    rows = (
        await session.scalars(
            select(Investigation).where(
                Investigation.document_id == document_id, Investigation.field_path == field_path, Investigation.outcome == "pending", Investigation.status == "done"
            )
        )
    ).all()
    for row in rows:
        took = _norm(corrected_value) == _norm(row.suggested_value) if row.action == "corregir_dato" else reason_code == "confirmed_correct"
        row.outcome, row.resolved_at = ("accepted" if took else "overridden"), datetime.now(UTC)


def _norm(value: Any) -> str:
    text = str(value if not isinstance(value, dict) else value.get("value")).strip().lower()
    try:
        return repr(float(text.replace(",", "")))
    except ValueError:
        return " ".join(text.split())
