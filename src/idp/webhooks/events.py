"""Domain events (VRT-28). Events are *thin*: identifiers, statuses and
links — never document contents or personal data. A consumer that needs the
detail fetches ``GET /v1/cases/{id}/result`` with its own credentials, so a
webhook never moves personal data outside an authorised call.

The wire format is CloudEvents 1.0 (structured JSON); the same envelope
will carry events on a bus in VRT-49."""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from idp.persistence.models import BulkJob, Case, CaseRun, OutboxEvent

SOURCE = "veritium"

CASE_RUN_COMPLETED = "pe.veritium.case.run.completed"
CASE_RUN_FAILED = "pe.veritium.case.run.failed"
CASE_VERDICT_CHANGED = "pe.veritium.case.verdict.changed"
BULK_JOB_COMPLETED = "pe.veritium.bulk_job.completed"
WEBHOOK_TEST = "pe.veritium.webhook.test"

EVENT_TYPES = (CASE_RUN_COMPLETED, CASE_RUN_FAILED, CASE_VERDICT_CHANGED, BULK_JOB_COMPLETED, WEBHOOK_TEST)


def _links(case_id: Any) -> dict[str, str]:
    return {"case": f"/v1/cases/{case_id}", "result": f"/v1/cases/{case_id}/result"}


def _emit(session: AsyncSession, *, tenant: str, type_: str, subject: str | None, data: dict[str, Any]) -> OutboxEvent:
    event = OutboxEvent(tenant=tenant, type=type_, subject=subject, data=data)
    session.add(event)
    return event


def emit_run_finished(session: AsyncSession, case: Case, run: CaseRun) -> OutboxEvent:
    data: dict[str, Any] = {
        "case_id": str(case.id),
        "external_ref": case.external_ref,
        "run_number": run.run_number,
        "trigger": run.trigger,
        "status": run.status,
        "verdict": run.verdict,
        "links": _links(case.id),
    }
    if run.status == "failed":
        # The error type only: the message can echo document content.
        data["error_type"] = (run.error or "").split(":", 1)[0] or None
    type_ = CASE_RUN_FAILED if run.status == "failed" else CASE_RUN_COMPLETED
    return _emit(session, tenant=case.tenant, type_=type_, subject=str(case.id), data=data)


def emit_verdict_changed(session: AsyncSession, case: Case, *, previous: str | None, reason_kinds: list[str]) -> OutboxEvent:
    return _emit(
        session,
        tenant=case.tenant,
        type_=CASE_VERDICT_CHANGED,
        subject=str(case.id),
        data={
            "case_id": str(case.id),
            "external_ref": case.external_ref,
            "previous_verdict": previous,
            "verdict": case.verdict,
            "reason_kinds": reason_kinds,
            "links": _links(case.id),
        },
    )


def emit_bulk_job_completed(session: AsyncSession, job: BulkJob, *, outcomes: dict[str, int]) -> OutboxEvent:
    """``outcomes``: how many cases ended with each verdict, plus ``failed``."""
    return _emit(
        session,
        tenant=job.tenant,
        type_=BULK_JOB_COMPLETED,
        subject=str(job.id),
        data={
            "bulk_job_id": str(job.id),
            "name": job.name,
            "cases": sum(outcomes.values()),
            "outcomes": outcomes,
            "links": {"bulk_job": f"/v1/bulk-jobs/{job.id}", "results": f"/v1/bulk-jobs/{job.id}/results"},
        },
    )


def cloudevent(event: OutboxEvent) -> dict[str, Any]:
    created = event.created_at.astimezone(UTC) if event.created_at else None
    return {
        "specversion": "1.0",
        "id": str(event.id),
        "source": SOURCE,
        "type": event.type,
        "subject": event.subject,
        "time": created.isoformat().replace("+00:00", "Z") if created else None,
        "datacontenttype": "application/json",
        "data": event.data,
    }


def body_bytes(event: OutboxEvent) -> bytes:
    """Deterministic serialisation — every attempt sends, and signs, the
    same bytes."""
    return json.dumps(cloudevent(event), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
