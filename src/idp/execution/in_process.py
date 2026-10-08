"""Interim executor (VRT-26): the run executes inside the API process, as a
background task — documents in parallel, but **not durable**: if the process
stops mid-run, the run is left unfinished. For development, and until the
aeon executor is deployed."""

from __future__ import annotations

import uuid

from fastapi import BackgroundTasks

from idp.config import Settings
from idp.pipeline.orchestrator import process_case_run


class InProcessExecutor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def submit(self, *, case_id: uuid.UUID, run_id: uuid.UUID, channel: str, background: BackgroundTasks) -> str | None:
        background.add_task(process_case_run, settings=self._settings, case_id=case_id, run_id=run_id)
        return None
