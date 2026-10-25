"""Editing a process against real Postgres (VRT-87): saving a draft again
keeps it one draft instead of a new version per save, a published version
never changes, and the name changes without a version."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


@pytest.mark.asyncio
async def test_a_draft_is_edited_in_place_and_a_published_version_is_not(live_settings):
    async with get_session_factory(live_settings)() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()
    key = f"prueba-borrador-{uuid.uuid4().hex[:6]}"
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
        admin = {"Authorization": f"Bearer {token}"}
        base = (await client.get("/v1/profiles/ad-hoc/versions/1", headers=admin)).json()["definition"]
        assert (await client.post("/v1/profiles", json={"key": key, "name": "Prueba"}, headers=admin)).status_code == 201
        try:
            draft = (await client.post(f"/v1/profiles/{key}/versions", json=base, headers=admin)).json()
            assert draft["version"] == 1 and draft["status"] == "draft"

            changed = {**base, "retention_days": 90}
            saved = await client.put(f"/v1/profiles/{key}/versions/1", json=changed, headers=admin)
            assert saved.status_code == 200, saved.text
            assert saved.json()["version"] == 1 and saved.json()["definition"]["retention_days"] == 90
            versions = (await client.get(f"/v1/profiles/{key}", headers=admin)).json()["versions"]
            assert [v["version"] for v in versions] == [1], "saving again does not pile up drafts"

            assert (await client.post(f"/v1/profiles/{key}/versions/1/publish", headers=admin)).status_code == 200
            assert (await client.put(f"/v1/profiles/{key}/versions/1", json=base, headers=admin)).status_code == 409

            renamed = await client.patch(f"/v1/profiles/{key}", json={"name": "Prueba renombrada", "description": "  "}, headers=admin)
            assert renamed.status_code == 200 and renamed.json()["name"] == "Prueba renombrada" and renamed.json()["description"] is None
            assert renamed.json()["active_version"] == 1, "the name is not part of a version"
        finally:
            await client.delete(f"/v1/profiles/{key}", headers=admin)
