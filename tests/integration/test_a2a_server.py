"""Veritium as an A2A agent against the real API, Postgres and MinIO
(VRT-52), without an LLM, through the official A2A client: the signed
Agent Card verifies against the published key; another agent opens a case
in one message, sees it wait for the missing evidence (input-required),
answers on the same task with a document, and gets the outcome as an
artifact; tasks are the caller's own; a task a restart left "working" is
settled from its run when read."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers import new_data_part, new_text_part
from a2a.types import AgentCard, GetTaskRequest, ListTasksRequest, Message, Part, Role, SendMessageRequest, Task, TaskState
from a2a.utils.signing import create_signature_verifier
from google.protobuf.json_format import MessageToDict, ParseDict
from jwt import PyJWK
from sqlalchemy import delete, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.config import get_settings
from idp.execution import handover
from idp.persistence.db import get_session_factory
from idp.persistence.models import A2ATask, Case, CaseRun, OutboxEvent
from idp.persistence.repositories import UserRepository
from idp.pipeline import orchestrator

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

BASE = "http://veritium.test"
_USERS = {"integracion": "test-a2a-integracion@example.com", "visor": "test-a2a-visor@example.com"}
_PASSWORD = "test-password-a2a"
TASK_IDS: list[str] = []


@pytest.fixture
def app(monkeypatch):
    async def nothing(*, session, document_id, document_repo, **_):
        await document_repo.set_status(document_id, "failed")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", nothing)
    for key, value in {"CASE_EXECUTOR": "in_process", "EVENT_BUS_BROKERS": "", "PUBLIC_API_BASE_URL": BASE, "A2A_POLL_INTERVAL_SECONDS": "0.1"}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


def _message(*parts: Part, task: Task | None = None) -> SendMessageRequest:
    message = Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER, parts=list(parts))
    if task is not None:
        message.task_id, message.context_id = task.id, task.context_id
    return SendMessageRequest(message=message)


def _pdf(name: str) -> Part:
    return Part(raw=b"%PDF-1.4 " + name.encode(), filename=name, media_type="application/pdf")


async def _send(client, request: SendMessageRequest) -> Task:
    task = None
    async for event in client.send_message(request):
        task = event.task if event.HasField("task") else task
    while handover.tasks:  # the in-process runs this test's messages started
        await asyncio.gather(*list(handover.tasks))
    assert task is not None
    TASK_IDS.append(task.id)
    return task


def _outcome(task: Task) -> dict:
    (result,) = [a for a in task.artifacts if a.artifact_id == "resultado"]
    return MessageToDict(result.parts[0].data)


@pytest.mark.asyncio
async def test_another_agent_delegates_a_case_to_veritium(live_settings, app):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        for role, email in _USERS.items():
            if await users.get_by_email(email) is None:
                await users.create(name=f"A2A {role}", email=email, password_hash=hash_password(_PASSWORD), role=role)
        await session.commit()
    ref = f"A2A-{uuid.uuid4().hex[:6]}"
    case_ids: list[uuid.UUID] = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE, timeout=60) as http:
            # The card is signed, and verifies against the published key.
            card_json = (await http.get("/.well-known/agent-card.json")).json()
            jwks = (await http.get("/.well-known/jwks.json")).json()
            card = ParseDict(card_json, AgentCard(), ignore_unknown_fields=True)
            verify = create_signature_verifier(lambda kid, jku: PyJWK(next(k for k in jwks["keys"] if k["kid"] == kid)), ["ES256"])
            verify(card)
            tampered = AgentCard()
            tampered.CopyFrom(card)
            tampered.description = "otra cosa"
            with pytest.raises(Exception):
                verify(tampered)

            assert (await http.post("/a2a/", json={"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "x"}})).status_code == 401

            tokens = {
                role: (await http.post("/auth/login", json={"email": email, "password": _PASSWORD})).json()["access_token"] for role, email in _USERS.items()
            }

            def client_for(role: str):
                agent_http = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url=BASE, timeout=60, headers={"Authorization": f"Bearer {tokens[role]}"}
                )
                return agent_http, ClientFactory(ClientConfig(httpx_client=agent_http, streaming=False)).create(card)

            agent_http, agent = client_for("integracion")
            reader_http, reader = client_for("visor")
            async with agent_http, reader_http:
                # Opening a case in one message: it waits for the evidence the process still needs.
                data = new_data_part({"profile": "convenios", "external_ref": ref, "process_data": {"nacionalidad": "PE"}})
                task = await _send(agent, _message(data, _pdf("solicitud.pdf")))
                assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED, MessageToDict(task)
                outcome = _outcome(task)
                case_ids.append(uuid.UUID(outcome["case_id"]))
                assert outcome["external_ref"] == ref and outcome["run_number"] == 1 and outcome["missing"]
                assert "Faltan:" in task.status.message.parts[0].text

                # Answering on the same task with a document runs the case again.
                again = await _send(agent, _message(new_text_part("Aquí va la boleta"), _pdf("boleta.pdf"), task=task))
                assert again.id == task.id and _outcome(again)["run_number"] == 2

                # An answer without documents keeps it waiting, and says why.
                empty = await _send(agent, _message(new_text_part("¿y ahora?"), task=task))
                assert empty.status.state == TaskState.TASK_STATE_INPUT_REQUIRED and "documento" in empty.status.message.parts[0].text

                # Without the process, nothing is opened.
                refused = await _send(agent, _message(_pdf("suelta.pdf")))
                assert refused.status.state == TaskState.TASK_STATE_REJECTED and "Falta el proceso" in refused.status.message.parts[0].text

                # The tasks are the caller's own.
                assert (await agent.get_task(GetTaskRequest(id=task.id))).status.state == TaskState.TASK_STATE_INPUT_REQUIRED
                listed = await agent.list_tasks(ListTasksRequest())
                assert {t.id for t in listed.tasks} >= {task.id, refused.id}
                assert task.id not in {t.id for t in (await reader.list_tasks(ListTasksRequest())).tasks}
                with pytest.raises(Exception):
                    await reader.get_task(GetTaskRequest(id=task.id))
                denied = await _send(reader, _message(data, _pdf("x.pdf")))
                assert denied.status.state == TaskState.TASK_STATE_REJECTED and "rol" in denied.status.message.parts[0].text

                # A task a restart left "working" settles from its run when read.
                async with factory() as session:
                    row = await session.get(A2ATask, task.id)
                    stale = ParseDict(row.snapshot, Task())
                    stale.status.state = TaskState.TASK_STATE_WORKING
                    row.snapshot, row.state = MessageToDict(stale), "TASK_STATE_WORKING"
                    await session.commit()
                settled = await agent.get_task(GetTaskRequest(id=task.id))
                assert settled.status.state == TaskState.TASK_STATE_INPUT_REQUIRED and _outcome(settled)["run_number"] == 2
    finally:
        async with factory() as session:
            ids = case_ids + list((await session.scalars(select(Case.id).where(Case.external_ref == ref))).all())
            await session.execute(delete(A2ATask).where(A2ATask.id.in_(TASK_IDS)))
            await session.execute(delete(OutboxEvent).where(OutboxEvent.subject.in_([str(i) for i in ids])))
            await session.execute(delete(CaseRun).where(CaseRun.case_id.in_(ids)))
            await session.execute(delete(Case).where(Case.id.in_(ids)))
            await session.commit()
