"""The profile designer's library against real Postgres (VRT-37): every
bindable rule of a catalog version — code, per-attribute format, CEL — with
the document types it runs on and the profiles already using it, plus the
retired-id map a new version needs."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


@pytest.mark.asyncio
async def test_the_library_lists_reusable_rules_with_where_they_run_and_who_uses_them(live_settings):
    async with get_session_factory(live_settings)() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
        response = await client.get("/v1/profiles/library", params={"catalog_version": 1}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    library = response.json()
    rules = {r["rule_id"]: r for r in library["rules"]}
    dni = rules["semantic.format.persona.dni"]
    assert dni["kind"] == "format" and {"insurance_disclosure", "loan_application"} <= set(dni["applies_to"])
    assert "convenios" in dni["used_by"]  # bound through the retired per-type ids
    assert library["legacy_rule_ids"]["self.loan_application_dni_format_valid"] == "semantic.format.persona.dni"
    assert any(t["key"] == "payslip" for t in library["document_types"])
    income = next(a for a in library["attributes"] if a["key"] == "ingreso.neto_mensual")
    assert {"document_type": "payslip", "role": "titular"} in income["providers"]
