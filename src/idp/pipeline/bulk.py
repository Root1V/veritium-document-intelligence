"""The bulk feeder (VRT-48): a bulk job's runs wait ``queued`` and are handed
to the executor a few at a time — at most ``bulk_max_in_flight`` across all
jobs — so a job of a thousand cases never crowds out online work, whatever
the executor. When a job has nothing left queued or in progress it is
finished and ``bulk_job.completed`` is emitted. Runs inside the API
process, like the webhook dispatcher; claims rows with SKIP LOCKED so
several instances can run it."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import exists, func, select

from idp.config import Settings
from idp.execution.handover import hand_over
from idp.persistence.db import get_session_factory
from idp.persistence.models import BulkJob, Case, CaseRun
from idp.webhooks.events import emit_bulk_job_completed

log = logging.getLogger(__name__)

_ACTIVE = ("queued", "pending", "running")
def outcome(case: Case) -> str:
    """What a bulk job's case came to: its verdict, ``failed``, or ``pending`` while it runs."""
    if case.status == "failed":
        return "failed"
    if case.status == "completed" and case.verdict:
        return case.verdict
    return "pending"


async def release(settings: Settings) -> int:
    """Hand queued runs to the executor while there is room. Returns how many."""
    async with get_session_factory(settings)() as session:
        bulk = select(Case.id).where(Case.bulk_job_id.is_not(None))
        in_flight = await session.scalar(select(func.count()).select_from(CaseRun).where(CaseRun.status.in_(("pending", "running")), CaseRun.case_id.in_(bulk)))
        room = settings.bulk_max_in_flight - (in_flight or 0)
        if room <= 0:
            return 0
        stmt = (
            select(CaseRun)
            .where(CaseRun.status == "queued")
            .order_by(CaseRun.created_at, CaseRun.id)
            .limit(room)
            .with_for_update(skip_locked=True)
        )
        runs = list((await session.scalars(stmt)).all())
        for run in runs:
            run.status = "pending"
        released = [(run.case_id, run.id) for run in runs]
        await session.commit()

    await hand_over(settings, released, channel="bulk")
    return len(released)


async def finish(settings: Settings) -> int:
    """Close the jobs with nothing left to do. Returns how many."""
    async with get_session_factory(settings)() as session:
        active = select(CaseRun.id).join(Case, Case.id == CaseRun.case_id).where(Case.bulk_job_id == BulkJob.id, CaseRun.status.in_(_ACTIVE))
        jobs = list((await session.scalars(select(BulkJob).where(BulkJob.finished_at.is_(None), ~exists(active)).with_for_update(skip_locked=True))).all())
        for job in jobs:
            cases = (await session.scalars(select(Case).where(Case.bulk_job_id == job.id))).all()
            job.finished_at = datetime.now(UTC)
            emit_bulk_job_completed(session, job, outcomes=dict(Counter(outcome(c) for c in cases)))
        await session.commit()
        return len(jobs)


async def run(settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            if released := await release(settings):
                log.info("cargas masivas: %d expediente(s) liberados", released)
            if finished := await finish(settings):
                log.info("cargas masivas: %d carga(s) terminadas", finished)
        except Exception:  # never let one bad tick stop the loop
            log.exception("bulk feeder tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.bulk_feed_interval_seconds)
        except TimeoutError:
            pass
