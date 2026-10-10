"""The discrepancy investigator against the real API, Postgres and MinIO
(VRT-66), with a scripted model: a reviewer asks to investigate a case's
findings; the agent reads the document with its tools and suggests a
correction backed by the document's text; the suggestion shows in the
review queue; correcting the field with the suggested value records it as
accepted, and the stats say so."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from synaptum.testing.fake import calls

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.llm import port
from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.parsing.store import save_parsed
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, Document, Investigation, ReviewItem, ValidationIssue
from idp.persistence.repositories import DocumentTypeRepository, ExtractionRepository, UserRepository
from idp.pipeline import investigation
from idp.storage.object_store import S3ObjectStore
from tests.unit.test_agentic_extraction import Script, _tool_results

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

_OPERATOR, _PASSWORD = "test-operador-investigador@example.com", "test-password-investigador"


def _env(value, region: int) -> dict:
    return {"value": value, "page": 0, "bbox": [0, 0, 1, 0.1], "confidence": 0.9, "source_text": str(value), "region_id": region}


@pytest.mark.asyncio
async def test_a_finding_is_investigated_and_its_suggestion_accepted(live_settings):
    factory = get_session_factory(live_settings)
    store = S3ObjectStore(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_OPERATOR) is None:
            await users.create(name="Operador Investigador", email=_OPERATOR, password_hash=hash_password(_PASSWORD), role="operador")
        catalog = await DocumentTypeRepository(session).load_catalog()
        version = catalog.current("payslip")
        assert version is not None
        case = Case(tenant="default", external_ref=f"INV-{uuid.uuid4().hex[:6]}", channel="backoffice", status="completed")
        session.add(case)
        await session.flush()
        key = f"default/{case.id}/test/boleta.pdf"
        document = Document(case_id=case.id, status="needs_review", document_type="payslip", storage_key=key, original_filename="boleta.pdf", needs_review=True)
        session.add(document)
        await session.flush()
        payload = {
            "employee_name": _env("PEREZ ROJAS ANA", 0), "employee_code": _env("0012845", 1), "period": _env("2026-09", 2),
            "gross_pay": _env(4000.0, 3), "total_deductions": _env(500.0, 4), "net_pay": _env(3500.0, 5), "concepts": [],
        }
        await ExtractionRepository(session).save(document_id=document.id, schema_version=str(version[0]), payload=payload, parser_backend="test", extraction_method="agentic")
        arithmetic = ValidationIssue(
            document_id=document.id, case_id=case.id, rule_id="self.payslip_arithmetic_consistency", category="self", field_path="net_pay",
            severity="error", message="El neto a pagar (3,500.00) no es igual al bruto menos los descuentos (3,400.00).", confidence=1.0,
            confidence_method="deterministic", explanation="x",
        )
        issue = ValidationIssue(
            document_id=document.id, case_id=case.id, rule_id="reference_data.employee_code_exists", category="reference_data", field_path="employee_code",
            severity="error", message="El código de empleado no existe en el maestro de empleados.", confidence=1.0, confidence_method="deterministic", explanation="x",
        )
        item = ReviewItem(document_id=document.id, field_path="employee_code", current_value={"value": "0012845"}, confidence=0.9, reason="validation_issue")
        session.add_all([issue, item, arithmetic])
        await session.commit()
        case_id, document_id, issue_id, item_id, arithmetic_id = case.id, document.id, issue.id, item.id, arithmetic.id
    parsed = ParsedDocument(
        backend="test", page_count=1,
        blocks=[
            ParsedBlock(region_id=0, text="Apellidos y Nombres : PEREZ ROJAS, ANA", page=0, bbox=[0, 0, 1, 0.1], confidence=0.9),
            ParsedBlock(region_id=1, text="Codigo AIRHSP: 0012345", page=0, bbox=[0, 0.1, 1, 0.2], confidence=0.9),
        ],
    )
    await asyncio.to_thread(save_parsed, store, key, parsed)

    script = Script(
        calls("search_document", document="d1", text="Codigo"),
        calls(
            "submit", id="c2", diagnosis="El código de la boleta es 0012345; se leyó 0012845.", cause="error_de_lectura", action="corregir_dato",
            document="d1", field="employee_code", value="0012345", confidence=0.85,
            evidence=[{"document": "d1", "page": 1, "text": "Codigo AIRHSP: 0012345"}],
        ),
        # The second finding: the correction it suggests is for a field nobody had flagged.
        calls(
            "submit", id="c3", diagnosis="El bruto se leyó 4000; el documento dice 3900.", cause="error_de_lectura", action="corregir_dato",
            document="d1", field="gross_pay", value="3900.00", confidence=0.7, evidence=[],
        ),
    )
    try:
        async with port.inference_lifespan(live_settings, model=script, models={"reasoning": "razonador", "vision": "vlm"}):
            async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
                token = (await client.post("/auth/login", json={"email": _OPERATOR, "password": _PASSWORD})).json()["access_token"]
                h = {"Authorization": f"Bearer {token}"}
                started = await client.post(f"/v1/cases/{case_id}/investigations", headers=h, json={"validation_issue_id": str(issue_id)})
                assert started.status_code == 202 and started.json()[0]["status"] == "running", started.text
                while investigation._launched:
                    await asyncio.gather(*list(investigation._launched))

                (done,) = (await client.get(f"/v1/cases/{case_id}/investigations", headers=h)).json()
                assert done["status"] == "done", done
                assert done["action"] == "corregir_dato" and done["suggested_value"] == "0012345" and done["document_id"] == str(document_id)
                assert done["cause_label"] == "Error de lectura del documento" and done["tools_used"] == ["search_document"]
                assert done["evidence"][0]["verified"] is True
                assert "Codigo AIRHSP: 0012345" in _tool_results(script.requests[1])[0], "the agent read the document through its tool"

                queue = (await client.get("/review", headers=h)).json()
                mine = next(i for i in queue if i["id"] == str(item_id))
                assert mine["suggestion"]["value"] == "0012345" and mine["suggestion"]["investigation_id"] == done["id"]

                fixed = await client.post(f"/review/{item_id}", headers=h, json={"corrected_value": "0012345", "reason_code": "ocr_misread"})
                assert fixed.status_code == 200, fixed.text
                (after,) = (await client.get(f"/v1/cases/{case_id}/investigations", headers=h)).json()
                assert after["outcome"] == "accepted"
                stats = (await client.get("/v1/investigations/stats", headers=h)).json()
                assert stats["accepted"] >= 1 and stats["acceptance_rate"] is not None

                # A suggested correction for a field without a review item opens one, so a person applies it through the queue.
                await client.post(f"/v1/cases/{case_id}/investigations", headers=h, json={"validation_issue_id": str(arithmetic_id)})
                while investigation._launched:
                    await asyncio.gather(*list(investigation._launched))
                queue = (await client.get("/review", headers=h)).json()
                opened = next(i for i in queue if i["document_id"] == str(document_id) and i["field_path"] == "gross_pay")
                assert opened["reason"] == "investigation" and opened["suggestion"]["value"] == "3900.00" and opened["current_value"]["value"] == 4000.0
    finally:
        async with factory() as session:
            await session.execute(delete(Investigation).where(Investigation.case_id == case_id))
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.commit()
