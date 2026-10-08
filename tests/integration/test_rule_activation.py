"""The activation gate of VRT-36 against the real API and Postgres: a rule
whose test cases do not give their expected outcome cannot be activated;
fixed, it can."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence.db import get_session_factory
from idp.persistence.models import ValidationRuleDefinition
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


@pytest.mark.asyncio
async def test_a_rule_is_activated_only_when_its_cases_pass(live_settings):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}
            created = await client.post("/validation-rules/manual", headers=h, json={
                "rule_id_suffix": suffix, "attribute": "ingreso.neto_mensual", "category": "self",
                "condition_cel": "value >= 1025.0", "severity": "error", "message_pass": "ok", "message_fail": "bajo",
                "test_cases": [
                    {"name": "alto", "input": {"value": 3000}, "expect": "pass"},
                    {"name": "mal esperado", "input": {"value": 500}, "expect": "pass"},
                ],
            })
            assert created.status_code == 200, created.text
            rule = created.json()
            assert rule["rule_id"] == f"custom.ingreso.neto_mensual.{suffix}" and rule["attribute"] == "ingreso.neto_mensual"

            tested = (await client.post(f"/validation-rules/{rule['id']}/test", headers=h)).json()
            assert not tested["all_ok"]
            refused = await client.post(f"/validation-rules/{rule['id']}/activate", headers=h)
            assert refused.status_code == 409 and "pass" in str(refused.json()["detail"])

            fixed = await client.patch(f"/validation-rules/{rule['id']}", headers=h, json={"test_cases": [
                {"name": "alto", "input": {"value": 3000}, "expect": "pass"},
                {"name": "bajo", "input": {"value": 500}, "expect": "fail"},
            ]})
            assert fixed.status_code == 200
            activated = await client.post(f"/validation-rules/{rule['id']}/activate", headers=h)
            assert activated.status_code == 200 and activated.json()["status"] == "active"
    finally:
        async with factory() as session:
            await session.execute(delete(ValidationRuleDefinition).where(ValidationRuleDefinition.rule_id.like(f"custom.%.{suffix}")))
            await session.commit()
