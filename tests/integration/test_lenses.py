"""Lenses against the real API, Postgres and MinIO (VRT-45), without an LLM:
the document's text is kept in storage as processing keeps it, and the
model is a stub. What is under test is the lifecycle — which lenses apply,
the reading, its citations resolved — and that Legal can edit a playbook."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.domain.lenses import ClauseAnswer, PlaybookAnswer
from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.parsing.store import save_parsed
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, LensRecord
from idp.persistence.repositories import CaseRepository, DocumentRepository, LensRepository, UserRepository
from idp.pipeline import lenses as lens_runner
from idp.storage.object_store import S3ObjectStore

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


@pytest.fixture
def stub_model(monkeypatch):
    seen: dict[str, str] = {}

    def ask(settings, lens, context):
        seen["context"] = context
        return PlaybookAnswer(
            headline="Falta la firma.",
            checks=[ClauseAnswer(item_key="irrevocable", status="cumple", explanation="Lo dice.", quote="de manera irrevocable", refs=["d1:2"])],
        )

    monkeypatch.setattr(lens_runner, "_ask", ask)
    return seen


@pytest.mark.asyncio
async def test_a_case_is_read_through_a_legal_lens_with_its_evidence(live_settings, stub_model):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
        await LensRepository(session).ensure_seed()
        case = await CaseRepository(session).create(external_ref=f"test-{uuid.uuid4()}")
        letter = await DocumentRepository(session).create(case_id=case.id, storage_key=f"default/test/{uuid.uuid4()}/carta.pdf", original_filename="carta.pdf")
        letter.document_type, letter.status = "authorization_letter", "completed"
        await session.commit()
        case_id, storage_key = case.id, letter.storage_key
    save_parsed(
        S3ObjectStore(live_settings),
        storage_key,
        ParsedDocument(backend="stub", page_count=1, blocks=[
            ParsedBlock(region_id=1, text="AUTORIZACIÓN DE DESCUENTO", page=0, bbox=[0.1, 0.1, 0.9, 0.15], confidence=0.9),
            ParsedBlock(region_id=2, text="Autorizo de manera irrevocable el descuento", page=0, bbox=[0.1, 0.2, 0.9, 0.25], confidence=0.9),
        ]),
    )

    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}

            applicable = {c["lens"]["key"]: c["applicable"] for c in (await client.get(f"/v1/cases/{case_id}/lenses", headers=h)).json()}
            assert applicable["legal_autorizacion_descuento"] and not applicable["legal_compra_deuda"]

            # ASGITransport runs the background reading before returning.
            started = await client.post(f"/v1/cases/{case_id}/lenses/legal_autorizacion_descuento", headers=h)
            assert started.status_code == 202, started.text
            latest = next(c["latest"] for c in (await client.get(f"/v1/cases/{case_id}/lenses", headers=h)).json() if c["lens"]["key"] == "legal_autorizacion_descuento")
            assert latest["status"] == "done", latest["error"]
            assert "[d1:2] Autorizo de manera irrevocable el descuento" in stub_model["context"]
            irrevocable = next(c for c in latest["output"]["checks"] if c["item_key"] == "irrevocable")
            assert irrevocable["quote_verified"] and irrevocable["evidence"][0]["bbox"] == [0.1, 0.2, 0.9, 0.25]
            assert irrevocable["evidence"][0]["document_id"] == str((await client.get(f"/v1/cases/{case_id}", headers=h)).json()["documents"][0]["id"])

            # Legal edits its playbook: the reading is now outdated.
            lenses = (await client.get("/v1/lenses", headers=h)).json()
            lens = next(x for x in lenses if x["key"] == "legal_autorizacion_descuento")
            lens["playbook"].append({"key": "fecha", "label": "Tiene fecha", "guidance": "", "importance": "baja"})
            assert (await client.put("/v1/lenses/legal_autorizacion_descuento", headers=h, json=lens)).status_code == 200
            latest = next(c["latest"] for c in (await client.get(f"/v1/cases/{case_id}/lenses", headers=h)).json() if c["lens"]["key"] == "legal_autorizacion_descuento")
            assert latest["outdated"]
    finally:
        async with factory() as session:
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.execute(delete(LensRecord).where(LensRecord.key == "legal_autorizacion_descuento"))
            await LensRepository(session).ensure_seed()  # back to the seed playbook
            await session.commit()
