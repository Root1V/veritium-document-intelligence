"""Editing the data catalog against real Postgres (VRT-89): saving a draft
again keeps it one draft instead of a new version per save, and a published
version never changes."""

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
async def test_a_catalog_draft_is_edited_in_place_and_a_published_version_is_not(live_settings):
    async with get_session_factory(live_settings)() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()
        (await users.get_by_email(_ADMIN)).platform_role = "admin"
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
        admin = {"Authorization": f"Bearer {token}"}
        active = (await client.get("/v1/semantic-catalog", headers=admin)).json()
        draft = (await client.post("/v1/semantic-catalog/versions", json=active["catalog"], headers=admin)).json()
        try:
            changed = {**active["catalog"], "roles": [*active["catalog"]["roles"], {"key": "prueba", "name": "Prueba", "definition": "Rol de prueba"}]}
            saved = await client.put(f"/v1/semantic-catalog/versions/{draft['version']}", json=changed, headers=admin)
            assert saved.status_code == 200, saved.text
            assert saved.json()["version"] == draft["version"] and saved.json()["catalog"]["roles"][-1]["key"] == "prueba"
            versions = (await client.get("/v1/semantic-catalog/versions", headers=admin)).json()
            assert [v["version"] for v in versions if v["status"] == "draft" and v["version"] >= draft["version"]] == [draft["version"]]

            broken = {**changed, "mappings": [{"document_type": "payslip", "field_path": "no_such_field", "attribute": "persona.dni", "role": "titular"}]}
            assert (await client.put(f"/v1/semantic-catalog/versions/{draft['version']}", json=broken, headers=admin)).status_code == 400

            published = await client.put(f"/v1/semantic-catalog/versions/{active['version']}", json=changed, headers=admin)
            assert published.status_code == 409
        finally:
            await client.delete(f"/v1/semantic-catalog/versions/{draft['version']}", headers=admin)
