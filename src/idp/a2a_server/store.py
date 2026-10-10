"""The A2A tasks in Postgres (VRT-52), scoped by owner: a caller only ever
sees its own tasks — another's is "not found", so existence is not leaked.

The SDK saves the task's snapshot on every event. The case run is the
truth about progress, though: if a restart cut the executor while a run
was going, the snapshot stays "working" — reading it then settles it from
the run (``outcome.final_status``), so a task never hangs."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

from a2a.server.context import ServerCallContext
from a2a.server.tasks import TaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict
from sqlalchemy import func, select

from idp.a2a_server.outcome import settle
from idp.config import Settings
from idp.persistence.db import get_session_factory
from idp.persistence.models import A2ATask
from idp.persistence.repositories import CaseRepository

_SETTLED = {TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_CANCELED, TaskState.TASK_STATE_REJECTED, TaskState.TASK_STATE_INPUT_REQUIRED}


def _owner(context: ServerCallContext) -> str:
    return context.user.user_name if context.user.is_authenticated else ""


def case_of(task: Task) -> uuid.UUID | None:
    value = task.metadata.fields.get("case_id")
    return uuid.UUID(value.string_value) if value is not None and value.string_value else None


class PostgresTaskStore(TaskStore):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def save(self, task: Task, context: ServerCallContext) -> None:
        owner = _owner(context)
        async with get_session_factory(self._settings)() as session:
            row = await session.get(A2ATask, task.id)
            if row is not None and row.owner != owner:
                return  # never overwrite someone else's task
            if row is None:
                row = A2ATask(id=task.id, context_id=task.context_id, owner=owner)
                session.add(row)
            row.case_id = case_of(task) or row.case_id
            row.state = TaskState.Name(task.status.state)
            row.snapshot = MessageToDict(task)
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def get(self, task_id: str, context: ServerCallContext) -> Task | None:
        async with get_session_factory(self._settings)() as session:
            row = await session.get(A2ATask, task_id)
            if row is None or row.owner != _owner(context):
                return None
            task = ParseDict(row.snapshot, Task(), ignore_unknown_fields=True)
            if task.status.state in _SETTLED or row.case_id is None:
                return task
            case = await CaseRepository(session).get(row.case_id)
            if case is None or (settled := await settle(session, task, case)) is None:
                return task
            row.state, row.snapshot, row.updated_at = TaskState.Name(settled.status.state), MessageToDict(settled), datetime.now(UTC)
            await session.commit()
            return settled

    async def list(self, params: ListTasksRequest, context: ServerCallContext) -> ListTasksResponse:
        size = params.page_size or 50
        offset = int(base64.urlsafe_b64decode(params.page_token).decode()) if params.page_token else 0
        stmt = select(A2ATask).where(A2ATask.owner == _owner(context))
        if params.context_id:
            stmt = stmt.where(A2ATask.context_id == params.context_id)
        if params.status:
            stmt = stmt.where(A2ATask.state == TaskState.Name(params.status))
        if params.HasField("status_timestamp_after"):
            stmt = stmt.where(A2ATask.updated_at > params.status_timestamp_after.ToDatetime(tzinfo=UTC))
        async with get_session_factory(self._settings)() as session:
            total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            rows = (await session.scalars(stmt.order_by(A2ATask.updated_at.desc(), A2ATask.id).offset(offset).limit(size))).all()
        more = offset + len(rows) < total
        return ListTasksResponse(
            tasks=[ParseDict(r.snapshot, Task(), ignore_unknown_fields=True) for r in rows],
            next_page_token=base64.urlsafe_b64encode(str(offset + len(rows)).encode()).decode() if more else "",
            page_size=size,
            total_size=total,
        )

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        async with get_session_factory(self._settings)() as session:
            row = await session.get(A2ATask, task_id)
            if row is not None and row.owner == _owner(context):
                await session.delete(row)
                await session.commit()
