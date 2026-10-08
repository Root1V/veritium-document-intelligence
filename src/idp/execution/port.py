"""``CaseExecutionPort``: hand a case run to whatever executes it. The API
only ever calls ``submit``; it never knows whether the run happens in its
own process or on aeon."""

from __future__ import annotations

import uuid
from typing import Protocol

from fastapi import BackgroundTasks

from idp.config import Settings


class CaseExecutionPort(Protocol):
    async def submit(self, *, case_id: uuid.UUID, run_id: uuid.UUID, channel: str, background: BackgroundTasks) -> str | None:
        """Start the run. Returns the executor's handle (stored as
        ``CaseRun.execution_ref``) or None when there is none."""
        ...


def executor_for(settings: Settings) -> CaseExecutionPort:
    if settings.case_executor == "aeon":
        from idp.execution.aeon import AeonExecutor

        return AeonExecutor(settings)
    from idp.execution.in_process import InProcessExecutor

    return InProcessExecutor(settings)
