"""Connected systems against the real API and Postgres (VRT-65): an admin
registers a system; it gets tokens with OAuth2 client credentials, calls
with role integracion within its quota; rotating or revoking stops the old
credentials at once."""

from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence.db import get_session_factory
from idp.persistence.models import ApiClient, User
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

_ADMIN, _PASSWORD = "test-admin-sistemas@example.com", "test-password-sistemas"


@pytest.mark.asyncio
async def test_a_system_connects_with_its_own_credentials(live_settings):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Admin Sistemas", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()

    created = None
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            admin = {"Authorization": f"Bearer {(await client.post('/auth/login', json={'email': _ADMIN, 'password': _PASSWORD})).json()['access_token']}"}
            response = await client.post("/v1/api-clients", headers=admin, json={"name": "Core de prueba", "rate_limit_per_minute": 3})
            assert response.status_code == 201, response.text
            created = response.json()
            cid, secret = created["client_id"], created["client_secret"]
            assert "client_secret" not in (await client.get("/v1/api-clients", headers=admin)).json()[0]
            assert all(u["email"] != f"{cid}@sistemas.veritium" for u in (await client.get("/users", headers=admin)).json()), "not listed as a person"

            async def token(**form) -> dict:
                r = await client.post("/auth/token", data={"grant_type": "client_credentials", **form})
                return {"status": r.status_code, **r.json()}

            assert (await token(client_id=cid, client_secret="otro"))["error"] == "invalid_client"
            assert (await client.post("/auth/token", data={"grant_type": "password"})).json()["error"] == "unsupported_grant_type"
            issued = await token(client_id=cid, client_secret=secret)
            assert issued["token_type"] == "Bearer" and issued["expires_in"] == live_settings.api_client_token_minutes * 60
            basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
            assert (await client.post("/auth/token", data={"grant_type": "client_credentials"}, headers={"Authorization": f"Basic {basic}"})).status_code == 200

            system = {"Authorization": f"Bearer {issued['access_token']}"}
            assert (await client.get("/v1/cases", headers=system)).status_code == 200
            assert (await client.get("/v1/api-clients", headers=system)).status_code == 403, "integracion is not admin"
            assert (await client.get("/v1/cases", headers=system)).status_code == 200
            over = await client.get("/v1/cases", headers=system)
            assert over.status_code == 429 and int(over.headers["Retry-After"]) > 0, "3 calls per minute"

            rotated = (await client.post(f"/v1/api-clients/{created['id']}/rotate", headers=admin)).json()
            assert (await client.get("/v1/cases", headers=system)).status_code == 401, "a token from before the rotation"
            assert (await token(client_id=cid, client_secret=secret))["status"] == 401
            fresh = {"Authorization": f"Bearer {(await token(client_id=cid, client_secret=rotated['client_secret']))['access_token']}"}

            assert (await client.post(f"/v1/api-clients/{created['id']}/revoke", headers=admin)).json()["revoked_at"]
            assert (await client.get("/v1/cases", headers=fresh)).status_code == 401
            assert (await token(client_id=cid, client_secret=rotated["client_secret"]))["status"] == 401
    finally:
        if created:
            async with factory() as session:
                user_id = await session.scalar(select(ApiClient.user_id).where(ApiClient.id == created["id"]))
                await session.execute(delete(ApiClient).where(ApiClient.id == created["id"]))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
