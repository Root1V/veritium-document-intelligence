"""Hand runs to the executor from outside a request (VRT-48, VRT-49): the
bulk feeder and the event consumer have no FastAPI ``BackgroundTasks`` of
their own. A run that cannot be started is marked failed; with the
in-process executor, the runs execute here as tasks."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import BackgroundTasks
from sqlalchemy import update

from idp.config import Settings
from idp.execution.port import executor_for
from idp.persistence.db import get_session_factory
from idp.persistence.models import CaseRun
from idp.pipeline.orchestrator import fail_run

# In-process runs: kept so they are not garbage-collected mid-run.
tasks: set[asyncio.Task] = set()


async def hand_over(settings: Settings, runs: list[tuple[uuid.UUID, uuid.UUID]], *, channel: str) -> None:
    """``runs``: (case_id, run_id) pairs, already committed as ``pending``."""
    background = BackgroundTasks()
    for case_id, run_id in runs:
        try:
            ref = await executor_for(settings).submit(case_id=case_id, run_id=run_id, channel=channel, background=background)
        except Exception as exc:
            await fail_run(settings, case_id, run_id, f"no se pudo iniciar la corrida: {type(exc).__name__}: {exc}")
            continue
        if ref is not None:
            async with get_session_factory(settings)() as session:
                await session.execute(update(CaseRun).where(CaseRun.id == run_id).values(execution_ref=ref))
                await session.commit()
    if background.tasks:
        task = asyncio.create_task(background())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
