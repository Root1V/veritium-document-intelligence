"""Selective reprocessing against the real API and Postgres (VRT-40),
without an LLM: extraction is a stub. A correction is written into the
extraction and re-evaluates only the rules that read the field — the other
rules' issues stay from the earlier run — re-extracting the document keeps
the human's correction, and a re-extraction that fails keeps the previous
extraction and says so in the run."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.config import get_settings
from idp.domain.envelope import Extracted
from idp.domain.schemas.payslip import PayslipSchema
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, CaseRun, OutboxEvent, ReferenceEmployee, ReviewItem, ValidationIssue
from idp.persistence.repositories import CaseRepository, CaseRunRepository, DocumentRepository, UserRepository
from idp.pipeline import orchestrator

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"
_ARITHMETIC, _CODE_EXISTS = "self.payslip_arithmetic_consistency", "reference_data.employee_code_exists"


def _payslip() -> dict:
    def e(value: Any) -> Any:
        return Extracted(value=value, page=0, confidence=0.99)

    return PayslipSchema(
        employee_name=e("PEREZ ROJAS, ANA"), employee_code=e("NOEXISTE"), period=e("09/2026"),
        gross_pay=e(1000.0), total_deductions=e(200.0), net_pay=e(700.0),  # the arithmetic fails, and stays failing
    ).model_dump(mode="json")


@pytest.fixture
def stub_extraction(monkeypatch):
    stub = {"fail": False}

    async def fake_process(*, session, document_id, extraction_repo, document_repo, **_):
        doc = await document_repo.get(document_id)
        if stub["fail"]:
            # as a real failure would: mid-way, after classification changed the type
            doc.document_type = "generic"
            await document_repo.set_status(document_id, "extracting")
            await session.commit()
            raise RuntimeError("409 idempotency-key-reuse")
        doc.document_type = "payslip"
        await extraction_repo.save(document_id=document_id, schema_version="1.0", payload=_payslip(), parser_backend="stub", extraction_method="fixed")
        await document_repo.set_status(document_id, "extracted")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", fake_process)
    monkeypatch.setenv("CASE_EXECUTOR", "in_process")
    get_settings.cache_clear()
    yield stub
    get_settings.cache_clear()


async def _active(session, case_id) -> dict[str, uuid.UUID | None]:
    rows = await session.scalars(select(ValidationIssue).where(ValidationIssue.case_id == case_id, ValidationIssue.superseded_at.is_(None)))
    return {i.rule_id: i.case_run_id for i in rows}


@pytest.mark.asyncio
async def test_a_correction_reevaluates_only_its_rules_and_survives_reextraction(live_settings, stub_extraction):
    factory = get_session_factory(live_settings)
    code = f"T{uuid.uuid4().hex[:8]}"
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
        session.add(ReferenceEmployee(employee_code=code, full_name="PEREZ ROJAS, ANA"))
        case = await CaseRepository(session).create(external_ref=f"test-{uuid.uuid4()}")
        doc = await DocumentRepository(session).create(case_id=case.id, storage_key="stub", original_filename="boleta.png")
        run1 = await CaseRunRepository(session).create_next(case, trigger="submit")
        await session.commit()
        case_id, doc_id, run1_id = case.id, doc.id, run1.id

    try:
        await orchestrator.process_case_run(settings=live_settings, case_id=case_id, run_id=run1_id)
        async with factory() as session:
            active = await _active(session, case_id)
            assert active[_ARITHMETIC] == run1_id and active[_CODE_EXISTS] == run1_id
            item = await session.scalar(select(ReviewItem).where(ReviewItem.document_id == doc_id, ReviewItem.field_path == "employee_code"))
            assert item is not None

        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}

            corrected = await client.post(f"/review/{item.id}", headers=h, json={"corrected_value": code, "reason_code": "ocr_misread"})
            assert corrected.status_code == 200 and corrected.json()["run_number"] == 2
            async with factory() as session:
                run2 = await session.scalar(select(CaseRun).where(CaseRun.case_id == case_id, CaseRun.run_number == 2))
                assert run2 is not None and run2.trigger == "correction" and run2.status == "completed"
                active = await _active(session, case_id)
                assert active[_ARITHMETIC] == run1_id, "a rule that does not read employee_code is not re-evaluated"
                assert _CODE_EXISTS not in active, "the corrected code exists: its issue is gone"
                document = await DocumentRepository(session).get(doc_id)
                assert document is not None and document.extraction is not None
                assert document.extraction.payload["employee_code"]["value"] == code
                assert _ARITHMETIC not in {r["rule_id"] for r in (run2.provenance or {})["rules"]}

            rejected = await client.post(f"/v1/cases/{case_id}/reprocess", headers=h, json={"kind": "rule", "rule_id": "no.existe"})
            assert rejected.status_code == 422
            reprocessed = await client.post(f"/v1/cases/{case_id}/reprocess", headers=h, json={"kind": "document", "document_id": str(doc_id)})
            assert reprocessed.status_code == 202 and reprocessed.json()["run_number"] == 3
            async with factory() as session:
                document = await DocumentRepository(session).get(doc_id)
                assert document is not None and document.extraction is not None
                assert document.extraction.payload["employee_code"]["value"] == code, "re-extraction keeps the correction"
                run3 = await session.scalar(select(CaseRun).where(CaseRun.case_id == case_id, CaseRun.run_number == 3))
                assert run3 is not None and run3.status == "completed" and run3.scope == {"kind": "document", "document_id": str(doc_id)}
                assert set((await _active(session, case_id)).values()) == {run3.id}

            stub_extraction["fail"] = True
            failed = await client.post(f"/v1/cases/{case_id}/reprocess", headers=h, json={"kind": "case"})
            assert failed.status_code == 202
            async with factory() as session:
                document = await DocumentRepository(session).get(doc_id)
                assert document is not None and document.extraction is not None and document.document_type == "payslip"
                assert document.extraction.payload["employee_code"]["value"] == code, "a failed re-extraction loses nothing"
                run4 = await session.scalar(select(CaseRun).where(CaseRun.case_id == case_id, CaseRun.run_number == 4))
                assert run4 is not None and run4.status == "completed" and "se conserva la extracción anterior" in (run4.error or "")
    finally:
        async with factory() as session:
            await session.execute(delete(OutboxEvent).where(OutboxEvent.subject == str(case_id)))
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.execute(delete(ReferenceEmployee).where(ReferenceEmployee.employee_code == code))
            await session.commit()
