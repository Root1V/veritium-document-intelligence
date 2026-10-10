"""The MCP Tasks extension (``io.modelcontextprotocol/tasks``, SEP-2663)
over Veritium's case runs (VRT-51). Creating or adding to a case takes
minutes; to a client that declared the extension, ``submit_case`` and
``add_documents`` answer with a task handle instead of waiting.

The task *is* the case run: its id is the run's id, and ``tasks/get`` reads
the run from the database. So a task is durable before the handle is
returned, survives restarts, and any API instance can answer for it — no
task store of its own. A run that ends with a verdict is ``completed``
(even a "return to client": that is an answer, not an error); a run that
stopped on an error is ``completed`` with ``isError`` too, since ``failed``
is reserved for JSON-RPC errors."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolRequestParams, CallToolResult, RequestParams, TextContent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.config import Settings
from idp.mcp_server.views import case_outcome
from idp.persistence.db import get_session_factory
from idp.persistence.models import CaseRun
from idp.persistence.repositories import CaseRepository

TASKS = "io.modelcontextprotocol/tasks"
TASK_TOOLS = ("submit_case", "add_documents")
_INVALID_PARAMS = -32602


class TaskParams(RequestParams):
    task_id: str  # taskId on the wire


def _iso(moment: datetime | None) -> str:
    return (moment or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _declared(ctx: ServerRequestContext[Any, Any]) -> bool:
    capabilities = ctx.session.client_capabilities
    return bool(capabilities and capabilities.extensions and TASKS in capabilities.extensions)


class CaseRunTasks(Extension):
    identifier = TASKS

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding("tasks/get", TaskParams, self._get),
            MethodBinding("tasks/update", TaskParams, self._ack),
            MethodBinding("tasks/cancel", TaskParams, self._ack),
        )

    async def intercept_tool_call(self, params: CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        result = await call_next(ctx)
        if params.name not in TASK_TOOLS or not _declared(ctx) or not isinstance(result, CallToolResult) or result.is_error:
            return result
        accepted = result.structured_content or {}
        async with get_session_factory(self._settings)() as session:
            run = await session.scalar(
                select(CaseRun).where(CaseRun.case_id == uuid.UUID(accepted["case_id"]), CaseRun.run_number == accepted["run_number"])
            )
            if run is None:
                return result
            return {"resultType": "task", **await self._task(session, run)}

    async def _task(self, session: AsyncSession, run: CaseRun) -> dict[str, Any]:
        case = await CaseRepository(session).get(run.case_id)
        assert case is not None
        outcome = await case_outcome(session, case)
        # The task is this run; if a later run superseded it, its outcome is still the case's.
        task: dict[str, Any] = {
            "taskId": str(run.id),
            "createdAt": _iso(run.created_at),
            "lastUpdatedAt": _iso(run.finished_at or run.started_at or run.created_at),
            "ttlMs": None,  # as durable as the case itself
            "pollIntervalMs": self._settings.mcp_task_poll_interval_ms,
        }
        if run.status not in ("completed", "failed"):
            return task | {"status": "working", "statusMessage": outcome.progress}
        tool_result = CallToolResult(
            content=[TextContent(type="text", text=outcome.model_dump_json(exclude_none=True))],
            structured_content=outcome.model_dump(mode="json"),
            is_error=run.status == "failed",
        )
        summary = outcome.verdict_label or "El proceso se detuvo por un error"
        return task | {"status": "completed", "statusMessage": summary, "result": tool_result.model_dump(mode="json", by_alias=True, exclude_none=True)}

    async def _run(self, session: AsyncSession, params: TaskParams) -> CaseRun:
        try:
            run = await session.get(CaseRun, uuid.UUID(params.task_id))
        except ValueError:
            run = None
        if run is None:
            raise MCPError(code=_INVALID_PARAMS, message="tarea desconocida", data={"taskId": params.task_id})
        return run

    async def _get(self, ctx: ServerRequestContext[Any, Any], params: TaskParams) -> HandlerResult:
        async with get_session_factory(self._settings)() as session:
            return {"resultType": "complete", **await self._task(session, await self._run(session, params))}

    async def _ack(self, ctx: ServerRequestContext[Any, Any], params: TaskParams) -> HandlerResult:
        """``tasks/update``: these tasks never ask for input. ``tasks/cancel``: a
        case run is not stopped halfway (it would leave the case without a
        verdict); cancellation is cooperative, so it is acknowledged and the
        task ends as it would have."""
        async with get_session_factory(self._settings)() as session:
            await self._run(session, params)
        return {"resultType": "complete"}
