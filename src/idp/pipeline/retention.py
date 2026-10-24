"""Removing a case's personal data (VRT-58, Ley 29733): on request of the
person it is about ("suprimido", by an admin) or when its process's
retention term runs out ("vencido", by the job below).

The case is anonymized, not deleted. What goes: the original files and the
OCR read from them, every value extracted or corrected, what search indexed
of both (VRT-59), the texts that quote them (findings, reasons, diagnoses,
lens readings, errors), the process data, and what other features copied
from the case (type suggestions, golden sets, A2A tasks, upload sessions).
What stays: the case, its process, dates,
status, verdict and the kinds of its reasons — so metrics and the record
that it existed and was removed survive — plus the log of who saw it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from idp.config import Settings
from idp.domain.process_profile import ProcessProfileDefinition
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import (
    A2ATask,
    AuditLogEntry,
    Case,
    CaseRun,
    DataAccess,
    Document,
    DocumentTypeSuggestion,
    EvalCase,
    Extraction,
    Investigation,
    LensResult,
    ProcessProfileVersion,
    ReviewItem,
    SearchChunk,
    SimulationResult,
    UploadSession,
    ValidationIssue,
)
from idp.storage.object_store import ObjectStore, S3ObjectStore

log = logging.getLogger(__name__)
REMOVED = "(datos suprimidos)"
_ACTIVE_RUNS = ("queued", "pending", "running")


class CaseBusy(Exception):
    """A run is under way: removing its data now would race it."""


def _reasons(reasons: list | None) -> list | None:
    """A reason keeps what kind it was and what it decided; its message quoted the data."""
    return [{**r, "message": REMOVED} for r in reasons] if reasons else reasons


async def anonymize_case(
    session: AsyncSession, store: ObjectStore, case: Case, *, reason: str, actor: str, role: str, channel: str, note: str | None = None
) -> int:
    """Remove the case's personal data, in the active unit; returns how many files went. Idempotent."""
    if await session.scalar(select(CaseRun.id).where(CaseRun.case_id == case.id, CaseRun.status.in_(_ACTIVE_RUNS)).limit(1)):
        raise CaseBusy("el expediente se está procesando; inténtalo cuando termine")
    documents = list((await session.scalars(select(Document).where(Document.case_id == case.id))).all())
    doc_ids = [d.id for d in documents]
    sessions = list((await session.scalars(
        select(UploadSession).where((UploadSession.case_id == case.id) | (UploadSession.submitted_case_id == case.id)).options(selectinload(UploadSession.files))
    )).all())
    golden = list((await session.scalars(select(EvalCase).where(EvalCase.source_document_id.in_(doc_ids)))).all()) if doc_ids else []

    keys = {k for d in documents if d.storage_key for k in (d.storage_key, f"{d.storage_key}.parsed.json")}
    keys |= {f.storage_key for s in sessions for f in s.files if f.storage_key}
    keys |= {g.storage_key for g in golden if g.storage_key}
    for key in sorted(keys):
        with contextlib.suppress(Exception):  # already gone, or never written
            await asyncio.to_thread(store.delete, key)

    await session.execute(delete(SearchChunk).where(SearchChunk.case_id == case.id))  # their values, text and the embeddings of both
    if doc_ids:
        await session.execute(delete(Extraction).where(Extraction.document_id.in_(doc_ids)))
        review_ids = select(ReviewItem.id).where(ReviewItem.document_id.in_(doc_ids))
        await session.execute(update(AuditLogEntry).where(AuditLogEntry.review_item_id.in_(review_ids)).values(original_value={}, corrected_value={}, justification=None))
        await session.execute(update(ReviewItem).where(ReviewItem.document_id.in_(doc_ids)).values(current_value={"value": None}))
    await session.execute(update(Document).where(Document.case_id == case.id).values(original_filename="documento suprimido", storage_key="", classification_reasoning=None))
    await session.execute(update(ValidationIssue).where(ValidationIssue.case_id == case.id).values(message=REMOVED, explanation=REMOVED, expected=None, actual=None))
    await session.execute(
        update(Investigation).where(Investigation.case_id == case.id).values(
            finding=REMOVED, diagnosis=None, suggested_value=None, evidence=None, trace=None, error=None
        )
    )
    await session.execute(update(LensResult).where(LensResult.case_id == case.id).values(output=None, error=None))
    await session.execute(update(SimulationResult).where(SimulationResult.case_id == case.id).values(added_reasons=[], removed_reasons=[], error=None))
    await session.execute(delete(DocumentTypeSuggestion).where(DocumentTypeSuggestion.case_id == case.id))
    await session.execute(delete(A2ATask).where(A2ATask.case_id == case.id))
    for g in golden:
        await session.delete(g)
    for s in sessions:
        s.request_input_payload = None
        for f in s.files:
            f.filename, f.storage_key = "archivo suprimido", ""
    for run in (await session.scalars(select(CaseRun).where(CaseRun.case_id == case.id))).all():
        run.verdict_reasons = _reasons(run.verdict_reasons)
        run.error = REMOVED if run.error else None

    case.request_input_payload = None
    case.verdict_reasons = _reasons(case.verdict_reasons)
    case.anonymized_at, case.anonymized_reason = datetime.now(UTC), reason
    action = "suprimir" if reason == "suprimido" else "vencer"
    session.add(DataAccess(action=action, what="datos personales del expediente", case_id=case.id, actor=actor, role=role, channel=channel, reason=note))
    await session.commit()
    log.info("datos personales: %s expediente %s (%d archivo(s)) por %s", action, case.id, len(keys), actor)
    return len(keys)


async def expire(settings: Settings, *, now: datetime | None = None) -> int:
    """Anonymize every case, of every unit, whose process's term ran out. Returns how many."""
    now = now or datetime.now(UTC)
    with tenancy.system():  # the job serves every business unit; each case is then handled in its own
        async with get_session_factory(settings)() as session:
            rows = (await session.execute(
                select(Case.id, Case.tenant, Case.created_at, Case.verdict_at, ProcessProfileVersion.definition)
                .join(ProcessProfileVersion, ProcessProfileVersion.id == Case.profile_version_id)
                .where(Case.anonymized_at.is_(None))
            )).all()
    due = []
    for case_id, tenant, created_at, verdict_at, definition in rows:
        days = ProcessProfileDefinition.model_validate(definition).retention_days
        if days is not None and (verdict_at or created_at) + timedelta(days=days) <= now:
            due.append((case_id, tenant))
    done = 0
    store = S3ObjectStore(settings)
    for case_id, tenant in due:
        with tenancy.acting_for(tenant):
            async with get_session_factory(settings)() as session:
                case = await session.get(Case, case_id)
                try:
                    await anonymize_case(session, store, case, reason="vencido", actor="sistema · conservación", role="sistema", channel="sistema",
                                         note="venció el plazo de conservación del proceso")
                    done += 1
                except CaseBusy:
                    await session.rollback()  # next time
    return done


async def run(settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            if expired := await expire(settings):
                log.info("conservación: %d expediente(s) anonimizados por plazo vencido", expired)
        except Exception:
            log.exception("conservación: la revisión falló")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.retention_check_minutes * 60)
