"""GET /v1/overview — the unit at a glance, for its home page (VRT-74).

Each number comes with what to compare it to (the previous period of the
same length), and the list of what needs a person comes with where to act.
Nothing here quotes a person's data: reasons are grouped by what failed
(the requirement, the rule, the attribute), never by the values involved.

- received: cases that arrived in the period.
- straight_through: of those with a verdict, the share decided "continue"
  with no field ever sent to a person.
- time_to_verdict: median from a case's arrival to its first verdict.
- daily: cases per arrival day, by their current decision.
- reasons: why cases did not decide themselves, most frequent first."""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_current_user, get_db_session
from idp.config import Settings
from idp.persistence.models import Case, CaseRun, Document, ReviewItem, ValidationRuleDefinition
from idp.pipeline.orchestrator import HARDCODED_RULE_DESCRIPTIONS

router = APIRouter(prefix="/v1/overview", tags=["overview"], dependencies=[Depends(get_current_user)])

Decision = Literal["continue", "human_review", "return_to_client"]
ATTENTION_LIMIT = 8

# What a rule's failure means, said briefly; its message quotes the case's data.
RULE_REASON = {
    "self.payslip_arithmetic_consistency": "El neto de la boleta no cuadra con bruto menos descuentos",
    "batch.employee_name_matches_insured_name": "El nombre de la boleta no coincide con el del seguro",
    "request_input.expected_employee_code_matches": "El código de empleado no es el esperado",
    "batch.duplicate_identifier": "Un identificador se repite entre documentos",
    "reference_data.employee_code_exists": "El código de empleado no está en el maestro",
    "reference_data.employee_name_matches_reference": "El nombre no está en el maestro de empleados",
    "external_system.insurance_policy_verified": "La póliza no se pudo verificar",
    "semantic.attribute_consistency": "Un dato no coincide entre documentos",
}


class Comparison(BaseModel):
    value: float | None
    previous: float | None


class DayCount(BaseModel):
    day: date
    continued: int = 0
    human_review: int = 0
    return_to_client: int = 0
    in_progress: int = 0


class ReasonCount(BaseModel):
    label: str
    decision: Decision
    count: int


class AttentionItem(BaseModel):
    kind: Literal["failed", "review", "client"]
    case_id: uuid.UUID
    case_ref: str
    title: str
    since: datetime


class Overview(BaseModel):
    days: int
    received: Comparison
    straight_through: Comparison  # 0..1
    decided: int  # the cases straight_through is a share of
    time_to_verdict_seconds: Comparison
    pending_review: int
    oldest_pending: datetime | None
    in_review: int
    waiting_client: int
    failed_documents: int
    daily: list[DayCount]
    reasons: list[ReasonCount]
    attention: list[AttentionItem]


def _rule_label(reason: dict, cel: dict[str, str]) -> str:
    rule_id = (reason.get("ref") or {}).get("rule_id", "")
    message = reason.get("message", "")
    if rule_id == "semantic.attribute_consistency" and " — " in message:
        return message.split(" — ")[0]  # "DNI del titular: los documentos no coinciden"; the values come after
    return RULE_REASON.get(rule_id) or cel.get(rule_id) or HARDCODED_RULE_DESCRIPTIONS.get(rule_id) or f"Regla {rule_id}"


def reason_label(reason: dict, cel: dict[str, str]) -> str | None:
    """A reason in words that quote no one's data, or None when it says nothing a person acts on."""
    kind = reason.get("kind")
    if kind in ("missing_document", "missing_evidence"):
        return reason.get("message")  # "Falta: <requirement>", from the process
    if kind == "failed_document":
        return "Un documento no se pudo leer"
    if kind == "rule":
        return _rule_label(reason, cel)
    return None  # pending_review: it is the consequence, not the cause


async def _window(session: AsyncSession, start: datetime, end: datetime) -> tuple[list, set[uuid.UUID], dict[uuid.UUID, datetime]]:
    rows = list((await session.execute(
        select(Case.id, Case.created_at, Case.verdict, Case.verdict_reasons).where(Case.created_at >= start, Case.created_at < end)
    )).all())
    ids = [r.id for r in rows]
    if not ids:
        return rows, set(), {}
    reviewed = set(await session.scalars(select(Document.case_id).join(ReviewItem, ReviewItem.document_id == Document.id).where(Document.case_id.in_(ids))))
    first = {case_id: at for case_id, at in (await session.execute(
        select(CaseRun.case_id, func.min(CaseRun.finished_at)).where(CaseRun.case_id.in_(ids), CaseRun.status == "completed").group_by(CaseRun.case_id)
    )).all()}
    return rows, reviewed, first


def _figures(rows: list, reviewed: set[uuid.UUID], first: dict[uuid.UUID, datetime]) -> tuple[int, int, float | None, float | None]:
    decided = [r for r in rows if r.verdict]
    straight = sum(1 for r in decided if r.verdict == "continue" and r.id not in reviewed)
    waits = [(first[r.id] - r.created_at).total_seconds() for r in rows if first.get(r.id)]
    return len(rows), len(decided), straight / len(decided) if decided else None, statistics.median(waits) if waits else None


async def _attention(session: AsyncSession, cel: dict[str, str]) -> tuple[list[AttentionItem], int, int, int]:
    failed = (await session.execute(
        select(Case.id, Case.external_ref, func.count(Document.id), func.max(Document.created_at))
        .join(Document, Document.case_id == Case.id)
        .where(Document.status == "failed", Case.anonymized_at.is_(None))
        .group_by(Case.id, Case.external_ref)
        .order_by(func.max(Document.created_at).desc())
    )).all()
    open_cases = (await session.execute(
        select(Case.id, Case.external_ref, Case.verdict, Case.verdict_reasons, Case.verdict_at)
        .where(Case.verdict.in_(("human_review", "return_to_client")), Case.anonymized_at.is_(None))
        .order_by(Case.verdict_at)
    )).all()

    def ref(case_id: uuid.UUID, external: str | None) -> str:
        return external or str(case_id)[:8]

    items = [
        AttentionItem(kind="failed", case_id=c, case_ref=ref(c, x), title="1 documento no se pudo leer" if n == 1 else f"{n} documentos no se pudieron leer", since=t) for c, x, n, t in failed
    ]
    for kind, verdict in (("review", "human_review"), ("client", "return_to_client")):
        for c in open_cases:
            if c.verdict != verdict:
                continue
            labels = [lbl for r in c.verdict_reasons or [] if (lbl := reason_label(r, cel))]
            title = labels[0] if labels else ("Tiene campos por revisar" if kind == "review" else "Espera documentos del cliente")
            items.append(AttentionItem(kind=kind, case_id=c.id, case_ref=ref(c.id, c.external_ref), title=title, since=c.verdict_at or datetime.now(UTC)))
    in_review = sum(1 for c in open_cases if c.verdict == "human_review")
    return items[:ATTENTION_LIMIT], in_review, len(open_cases) - in_review, sum(n for _, _, n, _ in failed)


@router.get("", response_model=Overview)
async def overview(
    days: int = Query(default=7, ge=1, le=90), session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_app_settings)
) -> Overview:
    zone = ZoneInfo(settings.business_timezone)
    today = datetime.now(zone).date()
    first_day = today - timedelta(days=days - 1)
    start = datetime.combine(first_day, datetime.min.time(), zone)
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), zone)
    cel = {r.rule_id: r.description_nl for r in (await session.scalars(select(ValidationRuleDefinition).where(ValidationRuleDefinition.kind == "cel"))).all() if r.description_nl}

    rows, reviewed, first = await _window(session, start, end)
    received, decided, straight, wait = _figures(rows, reviewed, first)
    p_received, _, p_straight, p_wait = _figures(*await _window(session, start - timedelta(days=days), start))

    daily = {first_day + timedelta(days=i): DayCount(day=first_day + timedelta(days=i)) for i in range(days)}
    reasons: Counter[tuple[str, str]] = Counter()
    for r in rows:
        bucket = daily[r.created_at.astimezone(zone).date()]
        field = {"continue": "continued", "human_review": "human_review", "return_to_client": "return_to_client"}.get(r.verdict or "", "in_progress")
        setattr(bucket, field, getattr(bucket, field) + 1)
        if r.verdict in ("human_review", "return_to_client"):
            for label in {lbl for reason in r.verdict_reasons or [] if (lbl := reason_label(reason, cel))}:
                reasons[(label, r.verdict)] += 1

    attention, in_review, waiting_client, failed_documents = await _attention(session, cel)
    pending, oldest = (await session.execute(select(func.count(ReviewItem.id), func.min(ReviewItem.created_at)).where(ReviewItem.status == "pending"))).one()
    return Overview(
        days=days,
        received=Comparison(value=received, previous=p_received),
        straight_through=Comparison(value=straight, previous=p_straight),
        decided=decided,
        time_to_verdict_seconds=Comparison(value=wait, previous=p_wait),
        pending_review=pending,
        oldest_pending=oldest,
        in_review=in_review,
        waiting_client=waiting_client,
        failed_documents=failed_documents,
        daily=list(daily.values()),
        reasons=[ReasonCount(label=label, decision=decision, count=n) for (label, decision), n in reasons.most_common(6)],
        attention=attention,
    )
