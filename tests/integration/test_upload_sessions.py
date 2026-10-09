"""Upload sessions against the real API, Postgres and MinIO (VRT-47),
without an LLM: the calling system opens a session; whoever has the link
uploads with its token and gets each file checked; a file that cannot be
read stays out; sending creates the case once."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy import delete, update

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.config import get_settings
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, OutboxEvent, UploadSession
from idp.persistence.repositories import CaseRepository, UserRepository
from idp.pipeline import orchestrator

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

_OPERATOR, _PASSWORD = "test-operador-carga@example.com", "test-password-carga"


def _page(blur: float = 0) -> bytes:
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    for y in range(80, 1680, 28):
        draw.text((60, y), "BOLETA DE PAGO  Neto a pagar 4,304.14  DNI 42785091", fill="black")
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def no_pipeline(monkeypatch):
    """The submitted case's run must not call a model: processing a document does nothing."""

    async def nothing(*, session, document_id, document_repo, **_):
        await document_repo.set_status(document_id, "failed")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", nothing)
    monkeypatch.setenv("CASE_EXECUTOR", "in_process")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_person_uploads_gets_answers_and_sends(live_settings, no_pipeline):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_OPERATOR) is None:
            await users.create(name="Operador Carga", email=_OPERATOR, password_hash=hash_password(_PASSWORD), role="operador")
            await session.commit()

    case_id = session_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            jwt = {"Authorization": f"Bearer {(await client.post('/auth/login', json={'email': _OPERATOR, 'password': _PASSWORD})).json()['access_token']}"}
            ref = f"test-carga-{uuid.uuid4().hex[:6]}"
            opened = await client.post("/v1/upload-sessions", headers=jwt, json={"profile": "convenios", "external_ref": ref, "process_data": {"nacionalidad": "PE"}})
            assert opened.status_code == 201, opened.text
            session_id, token = opened.json()["id"], opened.json()["token"]
            assert opened.json()["upload_url"].endswith(f"/carga/{session_id}#t={token}")
            h = {"X-Upload-Token": token}

            assert (await client.get(f"/v1/upload-sessions/{session_id}", headers={"X-Upload-Token": "otro"})).status_code == 404
            view = (await client.get(f"/v1/upload-sessions/{session_id}", headers=h)).json()
            assert view["process_name"] and any(r["key"] == "solicitud" and not r["covered"] for r in view["requirements"])

            good = await client.post(f"/v1/upload-sessions/{session_id}/files", headers=h, files={"file": ("boleta.png", _page(), "image/png")})
            assert good.status_code == 201 and good.json()["verdict"] == "ok", good.text
            blurred = (await client.post(f"/v1/upload-sessions/{session_id}/files", headers=h, files={"file": ("borrosa.png", _page(blur=4), "image/png")})).json()
            assert blurred["verdict"] == "reject" and blurred["checks"][0]["code"] == "blurry"
            letter = await client.post(
                f"/v1/upload-sessions/{session_id}/files", headers=h, data={"requirement_key": "autorizacion_descuento"},
                files={"file": ("carta.png", _page(), "image/png")},
            )
            assert letter.json()["requirement_key"] == "autorizacion_descuento"
            view = (await client.get(f"/v1/upload-sessions/{session_id}", headers=h)).json()
            assert next(r for r in view["requirements"] if r["key"] == "autorizacion_descuento")["covered"]

            removed = await client.delete(f"/v1/upload-sessions/{session_id}/files/{letter.json()['id']}", headers=h)
            assert [f["filename"] for f in removed.json()["files"]] == ["boleta.png", "borrosa.png"]

            sent = await client.post(f"/v1/upload-sessions/{session_id}/submit", headers=h)
            assert sent.status_code == 200, sent.text
            case_id = sent.json()["case_id"]
            assert sent.json() == {"case_id": case_id, "reference": ref, "files": 1}, "the blurred one stays out"
            assert (await client.post(f"/v1/upload-sessions/{session_id}/submit", headers=h)).json()["case_id"] == case_id, "sending twice: same case"
            late = await client.post(f"/v1/upload-sessions/{session_id}/files", headers=h, files={"file": ("tarde.png", _page(), "image/png")})
            assert late.status_code == 409

        async with factory() as session:
            case = await CaseRepository(session).get(uuid.UUID(case_id))
            assert case is not None and case.channel == "online" and [d.original_filename for d in case.documents] == ["boleta.png"]
            assert case.request_input_payload == {"nacionalidad": "PE"} and len(case.runs) == 1
            await session.execute(update(UploadSession).where(UploadSession.id == uuid.UUID(session_id)).values(status="open", expires_at=datetime.now(UTC) - timedelta(minutes=1)))
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            assert (await client.get(f"/v1/upload-sessions/{session_id}", headers=h)).status_code == 410
    finally:
        async with factory() as session:
            if session_id:
                await session.execute(delete(UploadSession).where(UploadSession.id == uuid.UUID(session_id)))
            if case_id:
                await session.execute(delete(OutboxEvent).where(OutboxEvent.subject == case_id))
                await session.execute(delete(Case).where(Case.id == uuid.UUID(case_id)))
            await session.commit()
