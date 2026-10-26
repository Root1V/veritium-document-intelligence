"""What can be done with a finding (VRT-105), against the real API and
Postgres: each one says whether its datum waits in the review queue, and
what the AI said when asked to look into it."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, Document, Investigation, ReviewItem, ValidationIssue
from idp.persistence.repositories import ProcessProfileRepository, UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]
_PASSWORD = "test-password-acciones"


@pytest.mark.asyncio
async def test_a_finding_says_its_review_and_what_the_ai_found(live_settings, scratch_unit):
    factory = get_session_factory(live_settings)
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            await ProcessProfileRepository(session).ensure_seed()
            version = ProcessProfileRepository.latest_published(await ProcessProfileRepository(session).get_by_key("convenios"))
            case = Case(status="completed", profile_version_id=version.id, external_ref="ACCIONES-1")
            session.add(case)
            await session.flush()
            doc = Document(case_id=case.id, status="needs_review", document_type="payslip", storage_key="x", original_filename="boleta.png", needs_review=True)
            session.add(doc)
            await session.flush()
            asked = ValidationIssue(case_id=case.id, document_id=doc.id, rule_id="r", category="reference_data", severity="warning", field_path="employee_code",
                                    message="El código no está en el maestro", confidence=1, confidence_method="rule", explanation="")
            alone = ValidationIssue(case_id=case.id, document_id=None, rule_id="semantic.attribute_consistency", category="cross_document", severity="error",
                                    field_path="titular.persona.dni", message="No coinciden", confidence=1, confidence_method="rule", explanation="")
            session.add_all([asked, alone])
            await session.flush()
            session.add_all([
                ReviewItem(document_id=doc.id, field_path="employee_code", current_value={"value": "123"}, confidence=0.9, reason="validation_issue"),
                Investigation(case_id=case.id, validation_issue_id=asked.id, rule_id="r", finding=asked.message, status="done",
                              diagnosis="El maestro usa otro código", action="confirmar_dato", created_by="prueba"),
            ])
            await UserRepository(session).create(name="Acciones", email=f"test-acciones-{scratch_unit}@example.com", password_hash=hash_password(_PASSWORD), role="operador")
            await session.commit()
            asked_id, alone_id = str(asked.id), str(alone.id)

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        token = (await client.post("/auth/login", json={"email": f"test-acciones-{scratch_unit}@example.com", "password": _PASSWORD})).json()["access_token"]
        issues = {i["id"]: i for i in (await client.get("/validation", headers={"Authorization": f"Bearer {token}"}, params={"limit": 500})).json()["issues"]}

    assert issues[asked_id]["review_status"] == "pending" and issues[asked_id]["review_item_id"]
    assert issues[asked_id]["investigation"] == {
        "id": issues[asked_id]["investigation"]["id"], "status": "done", "diagnosis": "El maestro usa otro código",
        "action_label": "Confirmar el dato como está", "outcome": "pending",
    }
    assert issues[alone_id]["review_status"] is None and issues[alone_id]["investigation"] is None, "nothing to review, nobody asked"
