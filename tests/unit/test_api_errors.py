"""What the API answers when the model fails (VRT-99): words a person can act on, not a bare 500."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from synaptum import NoObjectGeneratedError

from idp.api.app import create_app


@pytest.mark.asyncio
async def test_a_model_that_never_answers_in_shape_says_to_retry_or_rephrase():
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise NoObjectGeneratedError(
            "El modelo entregó 3 vez/veces en 3 turnos y ninguna validó."
        )

    app.router.routes.insert(
        0, app.router.routes.pop()
    )  # ahead of the mounts that take every path

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/boom")
    assert response.status_code == 502
    assert response.json()["detail"].startswith(
        "La IA no logró dar una respuesta válida"
    )
