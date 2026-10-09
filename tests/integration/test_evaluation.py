"""Evaluation suites against the real API, Postgres and MinIO (VRT-42),
without an LLM: parsing, classification and extraction are stubs whose
answer the test changes between runs, so what is under test is the suite
lifecycle — import, run, metrics and the comparison of two runs."""

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
from idp.persistence.db import get_session_factory
from idp.persistence.models import EvalSuite
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


@pytest.fixture
def stub_model(monkeypatch):
    """What the 'model' answers; the test edits it between runs."""
    answer: dict[str, Any] = {"type": "payslip", "net_pay": 4304.14}

    def e(value: Any) -> Any:
        return Extracted(value=value, page=0, confidence=0.8)

    monkeypatch.setattr(runner, "parse_example", lambda settings, data, filename: object())
    monkeypatch.setattr(
        runner, "classify_document", lambda settings, parsed, catalog, document_id: ClassificationResult(document_type=answer["type"], confidence=0.9, reasoning="")
    )
    monkeypatch.setattr(
        runner,
        "extract_document",
        lambda settings, parsed, document_type, catalog, document_id: ExtractionOutcome(
            schema_instance=PayslipSchema(
                employee_name=e("SALAS SIGUAS, KATERIN"), period=e("01/2026"), gross_pay=e(6618.0), total_deductions=e(2313.86), net_pay=e(answer["net_pay"])
            ),
            needs_review=False,
        ),
    )
    return answer


@pytest.mark.asyncio
async def test_a_suite_from_a_table_runs_and_compares(live_settings, stub_model):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()

    suite_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}

            template = await client.get("/v1/eval-suites/template", headers=h, params={"document_type": "payslip"})
            assert template.text.startswith("archivo,tipo,paginas,") and "net_pay" in template.text

            table = "archivo;tipo;net_pay;employee_name\nboleta.png;payslip;4,304.14;Salas Siguas, Katerín\n"
            bad = await client.post(
                "/v1/eval-suites", headers=h, data={"name": "Boletas"},
                files=[("table", ("casos.csv", table.encode(), "text/csv")), ("files", ("otra.png", b"x", "image/png"))],
            )
            assert bad.status_code == 422 and "'boleta.png' no está entre los archivos subidos" in bad.text

            created = await client.post(
                "/v1/eval-suites", headers=h, data={"name": f"Boletas {uuid.uuid4().hex[:6]}"},
                files=[("table", ("casos.csv", table.encode(), "text/csv")), ("files", ("boleta.png", b"png", "image/png"))],
            )
            assert created.status_code == 201, created.text
            suite = created.json()
            suite_id = suite["id"]
            assert suite["cases"][0]["expected_fields"] == {"net_pay": "4,304.14", "employee_name": "Salas Siguas, Katerín"}

            # ASGITransport runs the background task before the response returns: the run is done.
            first = (await client.post(f"/v1/eval-suites/{suite_id}/runs", headers=h)).json()
            run1 = (await client.get(f"/v1/eval-runs/{first['id']}", headers=h)).json()
            assert run1["status"] == "completed"
            assert run1["metrics"]["fields"] == {"evaluated": 2, "correct": 2, "accuracy": 1.0}
            assert run1["provenance"]["document_types"]["payslip"] >= 1

            stub_model["net_pay"] = 4304.0  # a worse "model"
            second = (await client.post(f"/v1/eval-suites/{suite_id}/runs", headers=h)).json()
            run2 = (await client.get(f"/v1/eval-runs/{second['id']}", headers=h, params={"baseline": first["id"]})).json()
            assert run2["metrics"]["fields"]["correct"] == 1
            assert [(c["field"], c["before"], c["after"]) for c in run2["comparison"]["regressions"]] == [("net_pay", 4304.14, 4304.0)]
            assert run2["comparison"]["improvements"] == []

            suites = (await client.get("/v1/eval-suites", headers=h)).json()
            assert next(s for s in suites if s["id"] == suite_id)["latest_run"]["id"] == second["id"]
    finally:
        if suite_id is not None:
            async with factory() as session:
                await session.execute(delete(EvalSuite).where(EvalSuite.id == uuid.UUID(suite_id)))
                await session.commit()


@pytest.mark.asyncio
async def test_a_golden_set_takes_what_the_reviewers_left_but_not_business_decisions(live_settings):
    from idp.persistence.models import AuditLogEntry, Case, ReviewItem
    from idp.persistence.repositories import CaseRepository, DocumentRepository

    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
        case = await CaseRepository(session).create(external_ref=f"test-{uuid.uuid4()}")
        doc = await DocumentRepository(session).create(case_id=case.id, storage_key="stub", original_filename=f"golden-{uuid.uuid4().hex[:6]}.png")
        doc.document_type = "payslip"
        for field, value, reason in (("net_pay", 4304.14, "ocr_misread"), ("employee_code", "999", "business_override")):
            item = ReviewItem(document_id=doc.id, field_path=field, current_value={"value": None}, confidence=0.4, reason="low_confidence", status="resolved")
            session.add(item)
            await session.flush()
            session.add(AuditLogEntry(review_item_id=item.id, original_value={"value": None}, original_confidence=0.4, reviewer_identity="t",
                                      corrected_value={"value": value}, reason_code=reason))
        await session.commit()
        case_id, doc_id = case.id, doc.id

    suite_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            created = await client.post("/v1/eval-suites/from-corrections", headers={"Authorization": f"Bearer {token}"}, json={"name": "Golden test"})
            assert created.status_code == 201, created.text
            suite_id = created.json()["id"]
            mine = next(c for c in created.json()["cases"] if c["source_document_id"] == str(doc_id))
            assert mine["expected_document_type"] == "payslip"
            assert mine["expected_fields"] == {"net_pay": 4304.14}, "a business override is a decision, not what the document says"
    finally:
        async with factory() as session:
            if suite_id is not None:
                await session.execute(delete(EvalSuite).where(EvalSuite.id == uuid.UUID(suite_id)))
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.commit()
