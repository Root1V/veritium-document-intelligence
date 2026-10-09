"""Governed prompt editing against the real API and Postgres (VRT-63),
without an LLM: only an AI specialist edits; a draft keeps the values the
platform fills in; an evaluation run tries it for that run only; it is
published after that evaluation (or an explicit acknowledgement for a
prompt no evaluation exercises); and going back is one call."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.classification.classifier import ClassificationResult
from idp.domain.envelope import Extracted
from idp.domain.schemas.payslip import PayslipSchema
from idp.evaluation import runner
from idp.extraction.base import ExtractionOutcome
from idp.llm.prompts import fingerprint, get, set_published
from idp.persistence.db import get_session_factory
from idp.persistence.models import EvalSuite, PromptEdit, PromptVersionRecord
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

_ADMIN, _AI, _PASSWORD = "test-admin-prompts@example.com", "test-ai@example.com", "test-password-ia"


@pytest.fixture
def stub_model(monkeypatch):
    seen: dict[str, Any] = {}

    def e(value: Any) -> Any:
        return Extracted(value=value, page=0, confidence=0.9)

    def classify(settings, parsed, catalog, document_id):
        seen["classify_text"] = get("classify").effective  # type: ignore[union-attr]
        return ClassificationResult(document_type="payslip", confidence=0.9, reasoning="")

    monkeypatch.setattr(runner, "parse_example", lambda settings, data, filename: object())
    monkeypatch.setattr(runner, "classify_document", classify)
    monkeypatch.setattr(
        runner, "extract_document",
        lambda *a, **kw: ExtractionOutcome(schema_instance=PayslipSchema(
            employee_name=e("ANA"), period=e("01/2026"), gross_pay=e(1.0), total_deductions=e(0.0), net_pay=e(1.0)), needs_review=False),
    )
    return seen


@pytest.mark.asyncio
async def test_a_prompt_change_is_drafted_tried_published_and_undone(live_settings, stub_model):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        for email, role in ((_ADMIN, "admin"), (_AI, "especialista_ia")):
            if await users.get_by_email(email) is None:
                await users.create(name=f"Test {role}", email=email, password_hash=hash_password(_PASSWORD), role=role)
        await session.commit()

    classify = get("classify")
    assert classify is not None
    draft_text = classify.text + "\nSi dudas entre dos tipos, elige el mas especifico."
    suite_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            async def login(email: str) -> dict[str, str]:
                token = (await client.post("/auth/login", json={"email": email, "password": _PASSWORD})).json()["access_token"]
                return {"Authorization": f"Bearer {token}"}

            admin, ai = await login(_ADMIN), await login(_AI)
            reason = "Mejora la elección entre tipos parecidos."

            assert (await client.put("/v1/prompts/classify/draft", headers=admin, json={"text": draft_text, "reason": reason})).status_code == 403
            broken = await client.put("/v1/prompts/classify/draft", headers=ai, json={"text": "Clasifica.", "reason": reason})
            assert broken.status_code == 422 and "falta {types}" in broken.text
            drafted = await client.put("/v1/prompts/classify/draft", headers=ai, json={"text": draft_text, "reason": reason})
            assert drafted.status_code == 200, drafted.text
            draft_id = drafted.json()["draft"]["id"]

            early = await client.post("/v1/prompts/classify/draft/publish", headers=ai, json={})
            assert early.status_code == 409 and "evaluación" in early.text

            # Try it in an evaluation run: in effect for that run only.
            table = "archivo;tipo;net_pay\nb.png;payslip;1\n"
            suite = (await client.post("/v1/eval-suites", headers=ai, data={"name": f"Prompts {uuid.uuid4().hex[:6]}"},
                                       files=[("table", ("t.csv", table.encode(), "text/csv")), ("files", ("b.png", b"x", "image/png"))])).json()
            suite_id = suite["id"]
            run = (await client.post(f"/v1/eval-suites/{suite_id}/runs", headers=ai, json={"prompt_drafts": [draft_id]})).json()
            assert stub_model["classify_text"] == draft_text
            detail = (await client.get(f"/v1/eval-runs/{run['id']}", headers=ai)).json()
            assert detail["provenance"]["prompts"]["classify"] == fingerprint(draft_text)
            assert classify.effective == classify.text, "outside the run, nothing changed"

            listed = next(p for p in (await client.get("/v1/prompts", headers=ai)).json() if p["name"] == "classify")
            assert listed["draft"]["evaluations"][0]["run_id"] == run["id"]

            published = await client.post("/v1/prompts/classify/draft/publish", headers=ai, json={})
            assert published.status_code == 200, published.text
            body = published.json()
            assert (body["source"], body["version"], body["published_reason"]) == ("edited", fingerprint(draft_text), reason)
            assert classify.effective == draft_text, "in effect from now on"

            undone = await client.post("/v1/prompts/classify/restore", headers=ai, json={"version": classify.code_version, "reason": "Volvemos al texto original."})
            assert undone.json()["source"] == "code" and classify.effective == classify.text

            # A prompt no evaluation exercises asks for an explicit acknowledgement.
            lens = get("lens_summary")
            assert lens is not None
            await client.put("/v1/prompts/lens_summary/draft", headers=ai, json={"text": lens.text + "\nSe breve.", "reason": reason})
            assert (await client.post("/v1/prompts/lens_summary/draft/publish", headers=ai, json={})).status_code == 409
            ok = await client.post("/v1/prompts/lens_summary/draft/publish", headers=ai, json={"acknowledge_no_evaluation": True})
            assert ok.status_code == 200 and ok.json()["source"] == "edited"
            await client.post("/v1/prompts/lens_summary/restore", headers=ai, json={"version": lens.code_version, "reason": "Volvemos al texto original."})
    finally:
        set_published({})
        async with factory() as session:
            if suite_id is not None:
                await session.execute(delete(EvalSuite).where(EvalSuite.id == uuid.UUID(suite_id)))
            await session.execute(delete(PromptEdit).where(PromptEdit.name.in_(["classify", "lens_summary"])))
            await session.execute(delete(PromptVersionRecord).where(PromptVersionRecord.source == "edited", PromptVersionRecord.name.in_(["classify", "lens_summary"])))
            await session.commit()
