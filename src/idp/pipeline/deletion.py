"""Deleting for good (VRT-72), to free space. Lesser cousin of retention.py:
anonymizing keeps the case as a record; deleting removes it — its rows go by
the database's cascades, its files from the object store — and leaves only a
line in the data access log saying who deleted it, when and why.

A stored file can be shared: a document's segments share the upload's, a
golden set made from corrections points at the document's, a submitted
upload session's files became the documents. So a file goes only once no
remaining row points at it (``purge``).

Also the technical housekeeping: events and their webhook deliveries,
finished A2A tasks and closed upload sessions go after
``technical_retention_days``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.config import Settings
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import A2ATask, BulkJob, Case, DataAccess, Document, EvalCase, OutboxEvent, UploadedFile, UploadSession, WebhookDelivery
from idp.persistence.repositories import CaseRunRepository
from idp.pipeline.retention import CaseBusy
from idp.storage.object_store import ObjectStore, S3ObjectStore

log = logging.getLogger(__name__)
_FINISHED_A2A = ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED")


async def purge(session: AsyncSession, store: ObjectStore, keys: set[str]) -> int:
    """Commit the deletions so far, then remove the files of ``keys`` that no
    remaining row points at (and what was read from them). Returns how many."""
    keys = {k for k in keys if k}
    await session.flush()
    if keys:
        for column in (Document.storage_key, EvalCase.storage_key, UploadedFile.storage_key):
            keys -= set(await session.scalars(select(column).where(column.in_(keys))))
    await session.commit()
    for key in sorted(keys):
        for name in (key, f"{key}.parsed.json"):
            with contextlib.suppress(Exception):  # already gone, or never written
                await asyncio.to_thread(store.delete, name)
    return len(keys)


async def _ensure_idle(session: AsyncSession, case_id: uuid.UUID) -> None:
    if await CaseRunRepository(session).has_active_run(case_id):
        raise CaseBusy("el expediente se está procesando; inténtalo cuando termine")


async def _golden_from(session: AsyncSession, document_ids: list[uuid.UUID]) -> set[str]:
    """Golden-set cases copied from these documents quote their data: they go with them."""
    if not document_ids:
        return set()
    golden = list((await session.scalars(select(EvalCase).where(EvalCase.source_document_id.in_(document_ids)))).all())
    for g in golden:
        await session.delete(g)
    return {g.storage_key for g in golden}


async def delete_case(session: AsyncSession, case: Case, *, actor: str, role: str, channel: str, note: str | None = None) -> set[str]:
    """Delete a case and everything of it, in the active unit, without
    committing; returns the files to ``purge``. Refused while a run is under way."""
    await _ensure_idle(session, case.id)
    documents = (await session.execute(select(Document.id, Document.storage_key).where(Document.case_id == case.id))).all()
    keys = {key for _, key in documents} | await _golden_from(session, [d for d, _ in documents])
    sessions = list((await session.scalars(
        select(UploadSession).where((UploadSession.case_id == case.id) | (UploadSession.submitted_case_id == case.id))
    )).all())
    if sessions:
        keys |= set(await session.scalars(select(UploadedFile.storage_key).where(UploadedFile.session_id.in_([s.id for s in sessions]))))
        await session.execute(delete(UploadSession).where(UploadSession.id.in_([s.id for s in sessions])))
    await session.execute(delete(A2ATask).where(A2ATask.case_id == case.id))
    session.add(DataAccess(action="eliminar", what="expediente completo", case_id=case.id, actor=actor, role=role, channel=channel, reason=note))
    await session.execute(delete(Case).where(Case.id == case.id))  # documents, runs, findings, conditions, index, readings: by cascade
    return keys


async def delete_document(session: AsyncSession, document: Document, *, actor: str, role: str, channel: str) -> set[str]:
    """Delete one document of a case (and its segments), without committing;
    returns the files to ``purge``. The caller re-evaluates the case."""
    await _ensure_idle(session, document.case_id)
    ids = [document.id, *await session.scalars(select(Document.id).where(Document.parent_document_id == document.id))]
    keys = {document.storage_key} | await _golden_from(session, ids)
    session.add(DataAccess(action="eliminar", what="un documento del expediente", case_id=document.case_id, document_id=document.id,
                           actor=actor, role=role, channel=channel))
    await session.execute(delete(Document).where(Document.id == document.id))  # its segments, extraction, findings, review, index: by cascade
    return keys


async def delete_bulk_job(session: AsyncSession, job: BulkJob, *, actor: str, role: str, channel: str) -> set[str]:
    """Delete a bulk job and its cases, without committing; returns the files to ``purge``."""
    cases = list((await session.scalars(select(Case).where(Case.bulk_job_id == job.id))).all())
    for case in cases:
        await _ensure_idle(session, case.id)
    keys: set[str] = set()
    for case in cases:
        keys |= await delete_case(session, case, actor=actor, role=role, channel=channel, note="se eliminó su carga masiva")
    await session.execute(delete(BulkJob).where(BulkJob.id == job.id))
    return keys


async def housekeep(settings: Settings, *, now: datetime | None = None) -> int:
    """Delete, in every unit, the technical records older than the term:
    events whose deliveries are over, finished A2A tasks, and closed upload
    sessions with the files that did not become documents. Returns how many rows."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.technical_retention_days)
    with tenancy.system():  # the job serves every business unit
        async with get_session_factory(settings)() as session:
            pending = exists().where(WebhookDelivery.event_id == OutboxEvent.id, WebhookDelivery.status == "pending")
            events = await session.execute(
                delete(OutboxEvent).where(OutboxEvent.created_at < cutoff, OutboxEvent.dispatched_at.is_not(None), ~pending)
            )
            tasks = await session.execute(delete(A2ATask).where(A2ATask.updated_at < cutoff, A2ATask.state.in_(_FINISHED_A2A)))
            closed = (UploadSession.status != "open") | (UploadSession.expires_at < cutoff)
            ids = list(await session.scalars(select(UploadSession.id).where(UploadSession.created_at < cutoff, closed)))
            keys = set(await session.scalars(select(UploadedFile.storage_key).where(UploadedFile.session_id.in_(ids)))) if ids else set()
            if ids:
                await session.execute(delete(UploadSession).where(UploadSession.id.in_(ids)))
            await purge(session, S3ObjectStore(settings), keys)
    return events.rowcount + tasks.rowcount + len(ids)
