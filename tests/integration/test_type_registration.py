"""Registering a reviewed type against real Postgres (VRT-33): the type is
published as v1 and its mappings become a new semantic catalog version; a
registration the catalog rejects leaves nothing behind."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence.db import get_session_factory
from idp.persistence.models import DocumentTypeRecord, SemanticCatalogVersion
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


def _definition(key: str) -> dict:
    return {
        "key": key, "display_name": "Recibo de prueba", "description": "Documento de prueba", "extraction_hint": "",
        "schema_title": "ReciboPruebaSchema",
        "fields": [{"name": "holder_dni", "type": "str", "required": True, "description": "DNI del titular"}],
    }


@pytest.mark.asyncio
async def test_register_publishes_the_type_and_its_mappings_and_a_rejection_leaves_no_trace(live_settings):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()
        catalog_versions_before = await session.scalar(select(func.max(SemanticCatalogVersion.version)))

    key, rejected_key = f"test_{uuid.uuid4().hex[:8]}", f"test_{uuid.uuid4().hex[:8]}"
    app = create_app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            rejected = await client.post("/v1/document-types/registrations", headers=headers, json={
                "definition": _definition(rejected_key), "mappings": [{"field_path": "holder_dni", "attribute": "persona.inexistente", "role": "titular"}]})
            assert rejected.status_code == 422

            ok = await client.post("/v1/document-types/registrations", headers=headers, json={
                "definition": _definition(key), "mappings": [{"field_path": "holder_dni", "attribute": "persona.dni", "role": "titular"}]})
            assert ok.status_code == 201, ok.text
            assert ok.json()["status"] == "published" and ok.json()["version"] == 1

            again = await client.post("/v1/document-types/registrations", headers=headers, json={"definition": _definition(key), "mappings": []})
            assert again.status_code == 409

        async with factory() as session:
            assert await session.scalar(select(DocumentTypeRecord).where(DocumentTypeRecord.key == rejected_key)) is None
            latest = await session.scalar(select(SemanticCatalogVersion).order_by(SemanticCatalogVersion.version.desc()).limit(1))
            assert latest.version == (catalog_versions_before or 0) + 1 and latest.status == "published"
            assert {"document_type": key, "field_path": "holder_dni", "attribute": "persona.dni", "role": "titular"} in latest.definition["mappings"]
    finally:
        async with factory() as session:
            await session.execute(delete(DocumentTypeRecord).where(DocumentTypeRecord.key.in_([key, rejected_key])))
            await session.execute(delete(SemanticCatalogVersion).where(SemanticCatalogVersion.version > (catalog_versions_before or 0)))
            await session.commit()
