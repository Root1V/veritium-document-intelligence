"""Corrections with a coded reason against the real API and Postgres
(VRT-39): the reason is required, some reasons require a justification,
and both land in the audit trail and its summary by reason and type."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, ReviewItem
from idp.persistence.repositories import CaseRepository, DocumentRepository, UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


@pytest.mark.asyncio
async def test_a_correction_needs_a_reason_and_it_is_audited(live_settings):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
        case = await CaseRepository(session).create(external_ref=f"test-{uuid.uuid4()}")
        doc = await DocumentRepository(session).create(case_id=case.id, storage_key="stub", original_filename="boleta.png")
        doc.document_type = "payslip"
        items = [ReviewItem(document_id=doc.id, field_path="net_pay", current_value={"value": 4304.0}, confidence=0.4, reason="low_confidence") for _ in range(2)]
        session.add_all(items)
        await session.commit()
        case_id, item_ids = case.id, [i.id for i in items]

    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}
            assert any(r["code"] == "business_override" and r["requires_justification"] for r in (await client.get("/review/reasons", headers=h)).json())

            no_reason = await client.post(f"/review/{item_ids[0]}", headers=h, json={"corrected_value": 4304.14})
            assert no_reason.status_code == 422
            unjustified = await client.post(f"/review/{item_ids[0]}", headers=h, json={"corrected_value": 4000, "reason_code": "business_override"})
            assert unjustified.status_code == 422 and "sustento" in unjustified.text

            ok = await client.post(f"/review/{item_ids[0]}", headers=h, json={"corrected_value": 4304.14, "reason_code": "ocr_misread", "justification": "Se leyó 4304.0"})
            assert ok.status_code == 200
            overridden = await client.post(
                f"/review/{item_ids[1]}", headers=h,
                json={"corrected_value": 4000, "reason_code": "business_override", "justification": "Se descuenta la gratificación"},
            )
            assert overridden.status_code == 200

            entries = (await client.get("/audit", headers=h, params={"limit": 200})).json()["entries"]
            mine = {e["reason_code"]: e for e in entries if e["field_path"] == "net_pay" and e["reason_code"] in ("ocr_misread", "business_override")}
            assert mine["ocr_misread"]["reason_label"] == "Error de lectura (OCR)" and mine["ocr_misread"]["justification"] == "Se leyó 4304.0"
            summary = (await client.get("/audit/correction-summary", headers=h)).json()
            assert any(r["reason_code"] == "business_override" and r["document_type"] == "payslip" and r["count"] >= 1 for r in summary)
    finally:
        async with factory() as session:
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.commit()
