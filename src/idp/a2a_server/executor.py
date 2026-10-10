"""Veritium as an A2A agent (VRT-52): a task is a case.

The first message opens it — a data part with the process (``profile``,
and optionally ``external_ref``, ``process_data``) plus the documents as
file parts, by reference (``url``, through the claim-check allow-list) or
inline (``raw``). The task then follows the case's run and ends as the run
does (outcome.py). When the verdict needs evidence the case lacks, the task
waits in ``input-required``; the caller's next message on the same task
brings the documents, which open a new run of the same case.

A message repeated with the same ``messageId`` by the same caller reuses
its case instead of opening another."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import time
import uuid
from typing import Any

from a2a.helpers import new_task
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Task, TaskState
from google.protobuf.json_format import MessageToDict

from idp.a2a_server.auth import WRITERS, VeritiumUser
from idp.a2a_server.outcome import ARTIFACT_ID, agent_message, artifact, final
from idp.a2a_server.store import case_of
from idp.api.case_contract import latest_run
from idp.api.case_outcome import case_outcome
from idp.api.case_service import CaseRefused, Upload, add_to_case, open_case
from idp.config import Settings
from idp.domain.case_progress import progress
from idp.events.claim_check import ClaimCheckError, fetch
from idp.execution.handover import hand_over
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import CaseRepository

log = logging.getLogger(__name__)
_TENANT = "default"  # multi-tenant arrives with VRT-57

EXPECTED = (
    "Envía una parte de datos con el proceso, p. ej. {\"profile\": \"convenios\", \"external_ref\": \"EXP-1\", "
    "\"process_data\": {\"nacionalidad\": \"PE\"}}, y los documentos como partes de archivo (url o contenido)."
)


async def _parse(settings: Settings, message: Message) -> tuple[dict[str, Any], list[Upload]]:
    data: dict[str, Any] = {}
    uploads: list[Upload] = []
    limit = settings.claim_check_max_file_mb * 1024 * 1024
    for i, part in enumerate(message.parts):
        kind = part.WhichOneof("content")
        if kind == "data":
            value = MessageToDict(part.data)
            if isinstance(value, dict):
                data |= value
        elif kind in ("raw", "url"):
            if kind == "raw":
                if len(part.raw) > limit:
                    raise CaseRefused(f"{part.filename or f'parte {i + 1}'}: pesa más de {settings.claim_check_max_file_mb} MB")
                content = part.raw
            else:
                try:
                    content = await fetch(settings, part.url)
                except ClaimCheckError as exc:
                    raise CaseRefused(str(exc)) from exc
            filename = part.filename or (part.url.rstrip("/").rsplit("/", 1)[-1] if kind == "url" else "") or f"documento-{i + 1}"
            media = part.media_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            uploads.append(Upload(filename=filename, content_type=media, content=content))
    return data, uploads


class CaseAgentExecutor(AgentExecutor):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        assert context.message is not None and context.task_id and context.context_id
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if context.current_task is None:
            await self._open(context, event_queue, updater)
        else:
            await self._continue(context, updater, context.current_task)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """A case's run is not stopped halfway — it would leave the case
        without a verdict. The task is cancelled; the case goes on."""

    async def _open(self, context: RequestContext, event_queue: EventQueue, updater: TaskUpdater) -> None:
        assert context.message is not None and context.task_id and context.context_id
        task = new_task(context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED, history=[context.message])
        user = context.call_context.user if context.call_context else None
        try:
            if not isinstance(user, VeritiumUser) or user.role not in WRITERS:
                raise CaseRefused(f"Tu rol ({user.role if isinstance(user, VeritiumUser) else 'sin identidad'}) no permite abrir expedientes.")
            data, uploads = await _parse(self._settings, context.message)
            if not data.get("profile"):
                raise CaseRefused(f"Falta el proceso. {EXPECTED}")
            key = f"a2a:{user.user_name}:{context.message.message_id}"
            async with get_session_factory(self._settings)() as session:
                cases = CaseRepository(session)
                case = await cases.get_by_idempotency_key(tenant=_TENANT, idempotency_key=key)
                fresh = case is None
                if case is None:
                    case, _ = await open_case(
                        self._settings, session, profile=str(data["profile"]), profile_version=data.get("profile_version"),
                        external_ref=data.get("external_ref"), channel=data.get("channel", "backoffice"), process_data=data.get("process_data"),
                        uploads=uploads, idempotency_key=key, tenant=_TENANT,
                    )
                    await session.commit()
                    case = await cases.get(case.id)
                assert case is not None
                run = latest_run(case)
                case_id, channel = case.id, case.channel
        except CaseRefused as refused:
            await event_queue.enqueue_event(task)
            await updater.reject(agent_message(refused.reason, task))
            return
        # The case is the task's: the store links them, and a restart can settle the task from it.
        task.metadata.update({"case_id": str(case_id)})
        task.status.message.CopyFrom(agent_message(f"Expediente {data.get('external_ref') or case_id} recibido.", task))
        await event_queue.enqueue_event(task)
        if fresh and run is not None:
            await hand_over(self._settings, [(case_id, run.id)], channel=channel)
        await self._follow(case_id, updater, task)

    async def _continue(self, context: RequestContext, updater: TaskUpdater, task: Task) -> None:
        case_id = case_of(task)
        if case_id is None:
            await updater.failed(agent_message("La tarea no tiene expediente.", task))
            return
        if task.status.state != TaskState.TASK_STATE_INPUT_REQUIRED:
            await updater.update_status(TaskState.TASK_STATE_WORKING, agent_message("El expediente sigue en revisión; espera su resultado.", task))
            return
        try:
            _, uploads = await _parse(self._settings, context.message)  # type: ignore[arg-type]
            if not uploads:
                raise CaseRefused("No llegó ningún documento. Envía los que faltan como partes de archivo.")
            async with get_session_factory(self._settings)() as session:
                case = await CaseRepository(session).get(case_id)
                if case is None:
                    raise CaseRefused("El expediente ya no existe.")
                run = await add_to_case(self._settings, session, case, uploads)
                await session.commit()
                pending, channel = [(case.id, run.id)], case.channel
        except CaseRefused as refused:
            await updater.requires_input(agent_message(refused.reason, task))
            return
        await updater.start_work(agent_message("Documentos recibidos; revisando el expediente de nuevo.", task))
        await hand_over(self._settings, pending, channel=channel)
        await self._follow(case_id, updater, task)

    async def _follow(self, case_id: uuid.UUID, updater: TaskUpdater, task: Task) -> None:
        """Report the run's progress until it ends, then the outcome. Past
        ``a2a_max_wait_minutes`` the task is left working: GetTask settles it."""
        deadline = time.monotonic() + self._settings.a2a_max_wait_minutes * 60
        last = None
        while time.monotonic() < deadline:
            async with get_session_factory(self._settings)() as session:
                case = await CaseRepository(session).get(case_id)
                if case is None:
                    await updater.failed(agent_message("El expediente ya no existe.", task))
                    return
                run = latest_run(case)
                if run is not None and run.status in ("completed", "failed"):
                    outcome = await case_outcome(session, case)
                    done, result = final(outcome), artifact(outcome)
                    await updater.add_artifact(list(result.parts), artifact_id=ARTIFACT_ID, name=result.name)
                    await updater.update_status(done.state, agent_message(done.text, task))
                    return
                now = progress(case.status, run.status if run else None, [d.status for d in case.documents]).current
            if now != last:
                await updater.update_status(TaskState.TASK_STATE_WORKING, agent_message(now, task))
                last = now
            await asyncio.sleep(self._settings.a2a_poll_interval_seconds)
        log.info("a2a: tarea %s sigue en curso tras la espera; se resolverá al consultarla", task.id)
