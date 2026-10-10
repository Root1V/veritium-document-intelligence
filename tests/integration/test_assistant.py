"""The user's assistant against the real API, Postgres and MCP server
(VRT-54), with a scripted model: a person asks about a case by its code;
the agent finds it through Veritium's MCP server with the person's token,
offered only the tools that read; its answer links the case it found and
never one it made up."""

from __future__ import annotations

import asyncio
import functools
import socket
import uuid

import httpx
import pytest
import uvicorn
from sqlalchemy import delete
from synaptum.testing.fake import calls

from idp.api import app as app_module
from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.config import get_settings
from idp.llm import port
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case
from idp.persistence.repositories import UserRepository
from tests.unit.test_agentic_extraction import Script, _tool_results

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

_VIEWER, _PASSWORD = "test-visor-asistente@example.com", "test-password-asistente"


@pytest.mark.asyncio
async def test_answers_about_a_case_through_mcp_with_the_persons_token(live_settings, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port_number = s.getsockname()[1]
    monkeypatch.setenv("PUBLIC_API_BASE_URL", f"http://127.0.0.1:{port_number}")
    monkeypatch.setenv("EVENT_BUS_BROKERS", "")
    get_settings.cache_clear()
    factory = get_session_factory(live_settings)
    ref = f"AST-{uuid.uuid4().hex[:6]}"
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_VIEWER) is None:
            await users.create(name="Visor Asistente", email=_VIEWER, password_hash=hash_password(_PASSWORD), role="visor")
        case = Case(tenant="default", external_ref=ref, channel="backoffice", status="completed", verdict="human_review")
        session.add(case)
        await session.commit()
        case_id = case.id
    made_up = str(uuid.uuid4())
    script = Script(
        calls("find_cases", external_ref=ref),
        calls("submit", id="c2", answer=f"El expediente {ref} está en revisión humana, como {made_up}."),
    )
    monkeypatch.setattr(app_module, "inference_lifespan", functools.partial(port.inference_lifespan, model=script, models={"reasoning": "razonador", "vision": "vlm"}))
    uv = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port_number, log_level="warning"))
    serving = asyncio.create_task(uv.serve())
    try:
        while not uv.started:
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port_number}", timeout=60) as client:
            token = (await client.post("/auth/login", json={"email": _VIEWER, "password": _PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}
            question = {"conversation": [{"role": "user", "text": f"¿Cómo va el {ref}?"}]}

            assert (await client.post("/v1/assistant/messages", json=question)).status_code in (401, 403)
            not_a_question = {"conversation": [{"role": "assistant", "text": "Hola"}]}
            assert (await client.post("/v1/assistant/messages", json=not_a_question, headers=h)).status_code == 422

            reply = await client.post("/v1/assistant/messages", json=question, headers=h)
            assert reply.status_code == 200, reply.text
            body = reply.json()
            assert body["answer"] == f"El expediente {ref} está en revisión humana, como .", "an id no tool returned is not shown"
            assert body["cases"] == [{"id": str(case_id), "label": ref}], "only a case a tool returned, and the answer names, becomes a link"
            assert body["consulted"] == ["Buscar expedientes"]

            offered = {t.name for t in script.requests[0].tools}
            assert {"find_cases", "get_case_status", "get_case_result", "get_field_evidence"} <= offered
            assert not offered & {"submit_case", "add_documents", "request_documents_link", "read_with_lens"}, "it only reads"
            assert ref in _tool_results(script.requests[1])[0], "the case came from the MCP server"
    finally:
        uv.should_exit = True
        await serving
        get_settings.cache_clear()
        async with factory() as session:
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.commit()
