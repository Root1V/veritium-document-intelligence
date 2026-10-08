"""The steps of a case run as Temporal activities (VRT-26). aeon schedules
them from the graph that idp.execution.aeon builds; this worker runs them.
Each one only wraps an idempotent orchestrator step: the args carry ids,
the state lives in Veritium's database."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from idp.config import Settings
from idp.execution.aeon import DOCUMENT_HEARTBEAT_SECONDS, EVALUATE, PROCESS_DOCUMENT, START_RUN
from idp.pipeline.orchestrator import evaluate_case, process_document, start_run


@contextlib.asynccontextmanager
async def _heartbeating(every: float) -> AsyncIterator[None]:
    """Heartbeat while the step runs. The blocking work (OCR, model calls)
    runs in threads, so the event loop stays free to send these."""

    async def beat() -> None:
        while True:
            activity.heartbeat()
            await asyncio.sleep(every)

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _guarded(step: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await step()
    except ValueError as exc:  # the case/run/document does not exist: retrying cannot help
        raise ApplicationError(str(exc), type="CaseRunNotFound", non_retryable=True) from exc


def _ids(args: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.UUID(args["case_id"]), uuid.UUID(args["run_id"])


class CaseActivities:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @activity.defn(name=START_RUN)
    async def start_run(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id, run_id = _ids(args)
        pending = await _guarded(lambda: start_run(self._settings, case_id, run_id))
        return {"pending_documents": len(pending)}

    @activity.defn(name=PROCESS_DOCUMENT)
    async def process_document(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id, run_id = _ids(args)
        document_id = uuid.UUID(args["document_id"])
        async with _heartbeating(DOCUMENT_HEARTBEAT_SECONDS / 3):
            await _guarded(lambda: process_document(self._settings, case_id, run_id, document_id))
        return {"document_id": str(document_id)}

    @activity.defn(name=EVALUATE)
    async def evaluate(self, args: dict[str, Any]) -> dict[str, Any]:
        case_id, run_id = _ids(args)
        verdict = await _guarded(lambda: evaluate_case(self._settings, case_id, run_id))
        return {"verdict": verdict}

    def all(self) -> list[Callable[..., Any]]:
        return [self.start_run, self.process_document, self.evaluate]
