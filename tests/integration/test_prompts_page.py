"""The read-only prompts page against the real API and Postgres (VRT-46):
every prompt in use with what it is for, its version and text, since when,
and how many runs used it."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.llm.prompts import current
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import PromptRepository, UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


@pytest.mark.asyncio
async def test_every_prompt_in_use_is_listed_with_its_version(live_settings):
    async with get_session_factory(live_settings)() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
            await session.commit()
        # What the API does when it starts.
        await PromptRepository(session).record([(p.name, p.version, p.text) for p in current()])

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
        prompts = {p["name"]: p for p in (await client.get("/v1/prompts", headers={"Authorization": f"Bearer {token}"})).json()}
    extraction = prompts["extract_agentic"]
    assert extraction["label"] == "Extracción de datos" and extraction["since"] is not None
    assert extraction["version"] == next(p.version for p in current() if p.name == "extract_agentic")
    assert set(extraction["placeholders"]) == {"hint", "regions", "schema", "grounding"}
    assert len(prompts) == len(current())
