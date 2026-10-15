"""Verifies Veritium's tools federated in aeon under Cedar (VRT-55), against the
running stacks — Veritium's API and scripts/aeon_dev.sh up:

1. aeon's catalog serves the approved tools (veritium.*) and not the one left
   out (request_documents_link).
2. Through aeon's MCP door: an allowed read reaches Veritium; a write is
   denied and never reaches it — proven on Veritium's side: the case it would
   have opened does not exist.
3. Through POST /execute as the assistant agent: the same, per agent.
4. aeon's tool-call log shows each call with its outcome.

    scripts/aeon_dev.sh verify-tools
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid

import httpx
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from sqlalchemy import select

from idp.config import get_settings
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case

TOOLGW = os.environ.get("AEON_TOOLGW_URL", "http://127.0.0.1:9413")
AGENT = "veritium-assistant@1.0.0"
READS = {"list_processes", "find_cases", "cases_overview", "get_case_status", "get_case_result", "get_field_evidence", "get_review_queue", "list_lenses", "quick_check_document"}
WRITES = {"submit_case", "add_documents", "read_with_lens"}
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'✓' if ok else '✗'} {what}")
    if not ok:
        failures.append(what)


async def case_exists(external_ref: str) -> bool:
    with tenancy.system():  # "never arrived" means in no business unit at all
        async with get_session_factory(get_settings())() as session:
            return await session.scalar(select(Case.id).where(Case.external_ref == external_ref)) is not None


def submit_args(ref: str) -> dict:
    return {"profile": "convenios", "external_ref": ref, "documents": [{"url": "s3://no-existe/x.pdf"}], "request_id": ref}


def _tool_log() -> subprocess.CompletedProcess[str]:
    query = (
        "SELECT door, tool_name, coalesce(agent_manifest_ref,''), outcome, coalesce(policy_id,'') FROM tool_invocations "
        "WHERE tool_name LIKE 'veritium.%' ORDER BY occurred_at DESC LIMIT 6"
    )
    cmd = ["docker", "compose", "-p", "veritium-aeon", "exec", "-T", "postgres", "psql", "-U", "aeon", "-d", "aeon", "-At", "-c", query]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


async def main(token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    print("1. Catálogo de aeon")
    http = create_mcp_http_client(headers=headers)
    async with http, Client(streamable_http_client(f"{TOOLGW}/mcp", http_client=http)) as mcp:
        names = {t.name for t in (await mcp.list_tools()).tools}
        served = {n.removeprefix("veritium.") for n in names if n.startswith("veritium.")}
        check(served == READS | WRITES, f"sirve las {len(READS | WRITES)} aprobadas (sirve: {sorted(served)})")
        check("veritium.request_documents_link" not in names, "no sirve request_documents_link, que no se aprobó")

        print("2. Puerta MCP (Cedar juzga al llamador autenticado, aeon INT-003c)")
        read = await mcp.call_tool("veritium.find_cases", {"limit": 1})
        # aeon forwards the source's result as it is (TOOL-010b): Veritium's own structured content.
        answer = read.structured_content or {}
        check(not read.is_error and "total" in answer, f"lectura permitida: find_cases llega a Veritium y responde ({answer.get('total')} expedientes)")
        ref = f"VRT55-MCP-{uuid.uuid4().hex[:6]}"
        write = await mcp.call_tool("veritium.submit_case", submit_args(ref))
        check(write.is_error and "denied" in " ".join(getattr(p, "text", "") for p in write.content), "escritura denegada por Cedar: submit_case")
        check(not await case_exists(ref), f"y nunca llegó: no existe el expediente {ref} en Veritium")

    print(f"3. POST /execute como {AGENT}")
    async with httpx.AsyncClient(base_url=TOOLGW, headers=headers, timeout=60) as client:
        ok = await client.post("/execute", json={"agent_manifest_ref": AGENT, "tool_name": "veritium.cases_overview", "args": {}})
        check(ok.status_code == 200 and "summary" in ok.text, f"lectura permitida: cases_overview ({ok.status_code})")
        ref = f"VRT55-EXEC-{uuid.uuid4().hex[:6]}"
        denied = await client.post("/execute", json={"agent_manifest_ref": AGENT, "tool_name": "veritium.submit_case", "args": submit_args(ref), "idempotency_key": ref})
        check(denied.status_code != 200 or "denied" in denied.text.lower(), f"escritura denegada: submit_case ({denied.status_code})")
        check(not await case_exists(ref), f"y nunca llegó: no existe el expediente {ref} en Veritium")

    print("4. Bitácora de aeon (tool_invocations)")
    rows = await asyncio.to_thread(_tool_log)
    print("  " + (rows.stdout.strip().replace("\n", "\n  ") or rows.stderr.strip()))
    check("denied" in rows.stdout and "ok" in rows.stdout, "registra las llamadas permitidas y las denegadas")

    print("\n" + ("TODO VERIFICADO" if not failures else f"FALLAN {len(failures)}: {json.dumps(failures, ensure_ascii=False)}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main(os.environ["AEON_TOOLS_TOKEN"]))
