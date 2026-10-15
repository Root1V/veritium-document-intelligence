"""The governed inference route (VRT-56), against a stand-in for aeon-modelgw:
Veritium asks for a profile, never a model; every call names the run it is
charged to and the agent whose budget it draws on — the case run's inside a
case step, its own run otherwise — with Veritium's aeon token and an
idempotency key; and a refusal for budget reads as such."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import BaseModel, SecretStr

from idp.config import Settings
from idp.llm.port import BudgetExceeded, Inference, charged_to


class Stub:
    def __init__(self, status: int = 200) -> None:
        self.seen: list[tuple[dict, dict]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                stub.seen.append(({k.lower(): v for k, v in self.headers.items()}, body))
                if status != 200:
                    payload = {"error": {"message": "budget exceeded: tokens", "type": "aeon_budget_exceeded"}}
                else:
                    payload = {"id": "x", "object": "chat.completion", "created": 0, "model": "gpt-oss-20b-mxfp4",
                               "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"kind": "boleta"}'}}],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                               "aeon": {"governed": True}}
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


class Kind(BaseModel):
    kind: str


def _settings(url: str) -> Settings:
    return Settings(_env_file=None, inference_route="governed", aeon_modelgw_url=url, aeon_api_token=SecretStr("token-de-veritium"))


@pytest.mark.asyncio
async def test_a_case_steps_calls_are_charged_to_its_run_and_others_to_their_own():
    stub = Stub()
    port = Inference(_settings(stub.url))
    await port.open()
    try:
        with charged_to("aeon-run-123", "veritium-case-run@1.0.0"):
            assert (await port.structured(purpose="classify", role="reasoning", output=Kind, instructions="clasifica", task="boleta")).kind == "boleta"
        await port.structured(purpose="draft_rule", role="reasoning", output=Kind, instructions="x", task="y")
    finally:
        await port.aclose()
        stub.server.shutdown()

    (case_headers, case_body), (own_headers, _) = stub.seen
    assert case_body["model"] == "veritium-reasoning", "a profile, never a model: aeon decides which one serves it"
    assert case_headers["authorization"] == "Bearer token-de-veritium"
    assert case_headers["x-aeon-run-id"] == "aeon-run-123" and case_headers["x-aeon-agent-manifest-ref"] == "veritium-case-run@1.0.0"
    assert case_headers["idempotency-key"].startswith("veritium/classify/"), "a retry after a crash does not pay twice"
    assert own_headers["x-aeon-run-id"].startswith("veritium-servicio-") and own_headers["x-aeon-agent-manifest-ref"] == "veritium-service@1.0.0"


@pytest.mark.asyncio
async def test_a_spent_budget_says_so():
    stub = Stub(status=402)
    port = Inference(_settings(stub.url))
    await port.open()
    try:
        with charged_to("aeon-run-9", "veritium-case-run@1.0.0"), pytest.raises(Exception) as caught:
            await port.structured(purpose="classify", role="reasoning", output=Kind, instructions="x", task="y")
    finally:
        await port.aclose()
        stub.server.shutdown()
    chain = [caught.value, caught.value.__cause__, caught.value.__context__]
    assert any(isinstance(e, BudgetExceeded) and "aeon-run-9" in str(e) for e in chain), chain
    assert len(stub.seen) == 1, "a spent budget is not retried"


def test_production_needs_the_governed_route():
    with pytest.raises(Exception, match="INFERENCE_ROUTE"):
        Settings(_env_file=None, environment="prod", jwt_secret_key="x" * 32, a2a_signing_key="k")
