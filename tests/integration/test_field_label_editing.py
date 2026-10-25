"""Naming the fields of a type against real Postgres (VRT-88): the published
version takes the labels in place, keeps its version and content hash, and
the catalog the web reads shows them."""

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
async def test_labels_change_in_place_without_a_new_version(live_settings):
    async with get_session_factory(live_settings)() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()
        (await users.get_by_email(_ADMIN)).platform_role = "admin"
        await session.commit()

    key = f"test_{uuid.uuid4().hex[:8]}"
    definition = {
        "key": key, "display_name": "Recibo de prueba", "description": "Documento de prueba", "schema_title": "ReciboPruebaSchema",
        "fields": [
            {"name": "holder_dni", "type": "str", "required": True, "description": "DNI del titular"},
            {"name": "lines", "type": "list", "item_name": "Line", "items": [{"name": "amount", "type": "float", "description": "Importe"}]},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
        admin = {"Authorization": f"Bearer {token}"}
        assert (await client.post("/v1/document-types", json=definition, headers=admin)).status_code == 201
        try:
            published = (await client.post(f"/v1/document-types/{key}/versions/1/publish", headers=admin)).json()

            named = await client.patch(f"/v1/document-types/{key}/labels", json={"labels": {"holder_dni": "DNI del titular", "lines[].amount": "Importe"}}, headers=admin)
            assert named.status_code == 200, named.text
            assert named.json()["version"] == 1 and named.json()["content_hash"] == published["content_hash"]

            web = next(t for t in (await client.get("/document-types", headers=admin)).json()["registered"] if t["name"] == key)
            fields = {f["name"]: f for f in web["fields"]}
            assert fields["holder_dni"]["label"] == "DNI del titular" and fields["lines"]["items"][0]["label"] == "Importe"

            cleared = await client.patch(f"/v1/document-types/{key}/labels", json={"labels": {"holder_dni": " "}}, headers=admin)
            assert cleared.json()["definition"]["fields"][0].get("label") is None
            assert (await client.patch(f"/v1/document-types/{key}/labels", json={"labels": {"nope": "x"}}, headers=admin)).status_code == 400
        finally:
            await client.delete(f"/v1/document-types/{key}", headers=admin)
