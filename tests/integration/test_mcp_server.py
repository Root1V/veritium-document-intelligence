"""The MCP server against the real API, Postgres and MinIO (VRT-51),
without an LLM, speaking the 2026-07-28 wire protocol as a client would:
no handshake, the protocol version and capabilities in every request's
``_meta``, routing headers, a bearer token. An agent learns what a process
asks for, opens a case with a document by claim-check and — having declared
the Tasks extension — gets a task it polls until the verdict; a client
without the extension gets the immediate answer; a reader cannot write;
without a token there is no access."""

from __future__ import annotations

import asyncio
import json
import socket
import uuid

import httpx
import pytest
import uvicorn
from sqlalchemy import delete, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.config import get_settings
from idp.execution import handover
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, CaseRun, OutboxEvent
from idp.persistence.repositories import UserRepository
from idp.pipeline import orchestrator
from idp.storage.object_store import S3ObjectStore

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

VERSION = "2026-07-28"
TASKS = "io.modelcontextprotocol/tasks"
_USERS = {"integracion": ("test-mcp-integracion@example.com", "test-password-mcp"), "visor": ("test-mcp-visor@example.com", "test-password-mcp")}


@pytest.fixture
def server(live_settings, monkeypatch):
    """The whole API on a free port, lifespan included (the MCP session manager runs in it)."""

    async def nothing(*, session, document_id, document_repo, **_):
        await document_repo.set_status(document_id, "failed")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", nothing)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    prefix = f"inbox-mcp-{uuid.uuid4().hex[:8]}/"
    monkeypatch.setenv("CASE_EXECUTOR", "in_process")
    monkeypatch.setenv("EVENT_BUS_BROKERS", "")
    monkeypatch.setenv("PUBLIC_API_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("CLAIM_CHECK_ALLOWED_PREFIXES", json.dumps([f"s3://{live_settings.storage_bucket}/{prefix}"]))
    get_settings.cache_clear()
    yield port, prefix
    get_settings.cache_clear()


async def _rpc(client: httpx.AsyncClient, token: str | None, method: str, params: dict, *, name: str | None = None, tasks: bool = False) -> httpx.Response:
    meta = {
        "io.modelcontextprotocol/protocolVersion": VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "prueba", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": {"extensions": {TASKS: {}}} if tasks else {},
    }
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": VERSION, "Mcp-Method": method}
    if name:
        headers["Mcp-Name"] = name
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": {**params, "_meta": meta}}
    return await client.post("/mcp", json=body, headers=headers)


def _result(response: httpx.Response) -> dict:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "error" not in payload, payload
    return payload["result"]


@pytest.mark.asyncio
async def test_an_agent_uses_veritium_through_mcp(live_settings, server):
    port, prefix = server
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        for role, (email, password) in _USERS.items():
            if await users.get_by_email(email) is None:
                await users.create(name=f"MCP {role}", email=email, password_hash=hash_password(password), role=role)
        await session.commit()
    S3ObjectStore(live_settings).put(f"{prefix}boleta.pdf", b"%PDF-1.4 boleta", content_type="application/pdf")
    document = {"url": f"s3://{live_settings.storage_bucket}/{prefix}boleta.pdf"}
    ref = f"MCP-{uuid.uuid4().hex[:6]}"

    uv = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(uv.serve())
    try:
        while not uv.started:
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
            tokens = {}
            for role, (email, password) in _USERS.items():
                tokens[role] = (await client.post("/auth/login", json={"email": email, "password": password})).json()["access_token"]
            writer, reader = tokens["integracion"], tokens["visor"]

            # Without a token: 401 pointing at the protected-resource metadata (RFC 9728), which names the issuer.
            refused = await _rpc(client, None, "tools/list", {})
            assert refused.status_code == 401 and "resource_metadata" in refused.headers["www-authenticate"]
            metadata = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
            issuer = metadata["authorization_servers"][0].rstrip("/")
            assert (await client.get("/.well-known/oauth-authorization-server")).json()["token_endpoint"] == f"{issuer}/auth/token"

            discovered = _result(await _rpc(client, writer, "server/discover", {}))
            assert TASKS in discovered["capabilities"]["extensions"]
            listed = _result(await _rpc(client, writer, "tools/list", {}))
            tools = {t["name"]: t for t in listed["tools"]}
            assert {"list_processes", "submit_case", "add_documents", "get_case_status", "get_case_result", "find_cases"} <= tools.keys()
            assert tools["get_case_result"]["annotations"]["readOnlyHint"] and "outputSchema" in tools["submit_case"]
            assert listed["ttlMs"] == 300_000

            processes = _result(await _rpc(client, writer, "tools/call", {"name": "list_processes", "arguments": {}}, name="list_processes"))
            convenios = next(p for p in processes["structuredContent"]["result"] if p["key"] == "convenios")
            assert convenios["requirements"] and "nacionalidad" in convenios["process_data"]

            # A reader cannot open cases.
            denied = _result(await _rpc(client, reader, "tools/call", {"name": "submit_case", "arguments": {"profile": "convenios", "documents": [document]}}, name="submit_case"))
            assert denied["isError"] and "rol" in denied["content"][0]["text"]

            # With the Tasks extension: a task handle, then polling until the verdict.
            args = {"profile": "convenios", "external_ref": ref, "process_data": {"nacionalidad": "PE"}, "documents": [document], "request_id": f"{ref}-1"}
            created = _result(await _rpc(client, writer, "tools/call", {"name": "submit_case", "arguments": args}, name="submit_case", tasks=True))
            assert created["resultType"] == "task" and created["status"] == "working" and created["ttlMs"] is None
            task_id = created["taskId"]
            while handover.tasks:
                await asyncio.gather(*list(handover.tasks))
            done = _result(await _rpc(client, writer, "tasks/get", {"taskId": task_id}, name=task_id))
            assert done["resultType"] == "complete" and done["status"] == "completed", done
            outcome = done["result"]["structuredContent"]
            assert outcome["external_ref"] == ref and outcome["status"] == "completed" and outcome["verdict"] and outcome["reasons"]
            assert _result(await _rpc(client, writer, "tasks/cancel", {"taskId": task_id}, name=task_id))["resultType"] == "complete"
            unknown = (await _rpc(client, writer, "tasks/get", {"taskId": str(uuid.uuid4())}, name="x")).json()
            assert unknown["error"]["code"] == -32602

            # The same request_id again: the same case, nothing new.
            again = _result(await _rpc(client, writer, "tools/call", {"name": "submit_case", "arguments": args}, name="submit_case"))
            assert again["structuredContent"]["case_id"] == outcome["case_id"]

            # Without the extension: the immediate answer.
            more = {"external_ref": ref, "documents": [{**document, "filename": "boleta-2.pdf"}], "request_id": f"{ref}-2"}
            added = _result(await _rpc(client, writer, "tools/call", {"name": "add_documents", "arguments": more}, name="add_documents"))
            assert added["resultType"] == "complete" and added["structuredContent"]["run_number"] == 2
            while handover.tasks:
                await asyncio.gather(*list(handover.tasks))

            status = _result(await _rpc(client, reader, "tools/call", {"name": "get_case_status", "arguments": {"case_id": outcome["case_id"]}}, name="get_case_status"))
            assert status["structuredContent"]["steps"][0].startswith("Recibido")
            found = _result(await _rpc(client, reader, "tools/call", {"name": "find_cases", "arguments": {"external_ref": ref}}, name="find_cases"))
            assert [c["case_id"] for c in found["structuredContent"]["result"]] == [outcome["case_id"]]
            uri = outcome["result_uri"]
            read = _result(await _rpc(client, reader, "resources/read", {"uri": uri}, name=uri))
            assert json.loads(read["contents"][0]["text"])["case"]["external_ref"] == ref
    finally:
        uv.should_exit = True
        await serving
        async with factory() as session:
            ids = list((await session.scalars(select(Case.id).where(Case.external_ref == ref))).all())
            await session.execute(delete(OutboxEvent).where(OutboxEvent.subject.in_([str(i) for i in ids])))
            await session.execute(delete(CaseRun).where(CaseRun.case_id.in_(ids)))
            await session.execute(delete(Case).where(Case.id.in_(ids)))
            await session.commit()
