"""A case's personal data (VRT-58) against the real API, Postgres and MinIO:
masked by default for everyone and on every screen that shows the case;
whoever works it asks to see them — one click, one record, for a while —
and the original file only then; a visor can't, nor search by a datum; a
system sees them per call, each call recorded."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import ApiClient, Case, DataAccess, Document, Extraction, ReviewItem, User, ValidationIssue
from idp.persistence.repositories import ProcessProfileRepository, UserRepository
from idp.storage.object_store import S3ObjectStore

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]
_PASSWORD = "test-password-datos"
DNI, NAME, NET = "42285866", "SALAS SIGUAS KATERIN KAROLA", 2500.0


def _env(value, text=None):
    return {"value": value, "confidence": 0.95, "source_text": text if text is not None else str(value), "page": 1}


@pytest.mark.asyncio
async def test_personal_data_are_masked_until_whoever_works_the_case_asks(live_settings, scratch_unit):
    factory = get_session_factory(live_settings)
    store = S3ObjectStore(live_settings)
    key = f"{scratch_unit}/{uuid.uuid4()}/boleta.png"
    store.put(key, b"imagen de la boleta", content_type="image/png")
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            await ProcessProfileRepository(session).ensure_seed()
            version = ProcessProfileRepository.latest_published(await ProcessProfileRepository(session).get_by_key("convenios"))
            case = Case(status="completed", profile_version_id=version.id, external_ref="DATOS-1", verdict="human_review",
                        verdict_reasons=[{"kind": "rule", "decision": "human_review", "ref": {"rule_id": "r"}, "message": f"El DNI {DNI} no figura en la planilla"}])
            session.add(case)
            await session.flush()
            doc = Document(case_id=case.id, status="needs_review", document_type="payslip", storage_key=key, original_filename="boleta.png", needs_review=True)
            session.add(doc)
            await session.flush()
            session.add_all([
                Extraction(document_id=doc.id, schema_version="1", parser_backend="rapidocr", extraction_method="agentic",
                           payload={"employee_name": _env(NAME), "employee_code": _env(DNI), "net_pay": _env(NET, "S/ 2,500.00")}),
                ValidationIssue(case_id=case.id, document_id=doc.id, rule_id="r", category="reference_data", severity="warning", field_path="employee_code",
                                message=f"El código {DNI} no está en el maestro", confidence=1, confidence_method="rule", explanation=f"{NAME} no figura"),
                ReviewItem(document_id=doc.id, field_path="net_pay", current_value=_env(NET), confidence=0.4, reason="low_confidence"),
            ])
            users = UserRepository(session)
            for role in ("operador", "visor"):
                await users.create(name=f"Datos {role}", email=f"test-datos-{role}-{scratch_unit}@example.com", password_hash=hash_password(_PASSWORD), role=role)
            await session.commit()
            case_id, doc_id = case.id, doc.id

    secrets = (DNI, "KATERIN", "2,500", "2500")
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            async def login(role: str) -> dict[str, str]:
                r = await client.post("/auth/login", json={"email": f"test-datos-{role}-{scratch_unit}@example.com", "password": _PASSWORD})
                return {"Authorization": f"Bearer {r.json()['access_token']}"}

            operador, visor = await login("operador"), await login("visor")
            screens = [f"/v1/cases/{case_id}", f"/v1/cases/{case_id}/result", f"/documents/{doc_id}", "/review", "/validation", f"/batches/{case_id}/entities"]

            # Everyone, by default: no datum of the case in any screen, in any form.
            for who in (operador, visor):
                for path in screens:
                    r = await client.get(path, headers=who)
                    assert r.status_code == 200, (path, r.text)
                    assert not [s for s in secrets if s.lower() in r.text.lower()], f"{path} shows personal data"
            assert "••••5866" in (await client.get(f"/v1/cases/{case_id}/result", headers=visor)).text, "masked, not removed: the last digits tell two apart"
            issues = (await client.get("/validation", headers=visor, params={"limit": 500})).json()["issues"]
            assert any(i["case_ref"] == "DATOS-1" for i in issues), "each finding names its case (VRT-104)"
            assert (await client.get(f"/documents/{doc_id}/file", headers=operador)).status_code == 403, "the original is all personal data"

            # A visor cannot ask to see them, nor find a case by a datum.
            assert (await client.post(f"/v1/cases/{case_id}/reveal", headers=visor)).status_code == 403
            assert (await client.get(f"/v1/cases/{case_id}/result", headers=visor, params={"reveal": "true"})).status_code == 403
            assert (await client.get("/documents", headers=visor, params={"q": DNI})).status_code == 403

            # The operador asks: one record, and for a while the case shows them — screens and original.
            opened = await client.post(f"/v1/cases/{case_id}/reveal", headers=operador, json={"reason": "revisar el ingreso"})
            assert opened.status_code == 200 and opened.json()["until"]
            for path in (f"/v1/cases/{case_id}/result", f"/documents/{doc_id}", "/review"):
                assert DNI in (await client.get(path, headers=operador)).text or "2500" in (await client.get(path, headers=operador)).text, path
            assert (await client.get(f"/documents/{doc_id}/file", headers=operador)).content == b"imagen de la boleta"
            assert not [s for s in secrets if s.lower() in (await client.get(f"/v1/cases/{case_id}/result", headers=visor)).text.lower()], "only for who asked"

            # A connected system sees them per call, each call recorded.
            system = await client.post("/v1/api-clients", headers=await _admin(client, factory, scratch_unit), json={"name": "Core de prueba"})
            creds = system.json()
            token = (await client.post("/auth/token", data={"grant_type": "client_credentials", "client_id": creds["client_id"], "client_secret": creds["client_secret"]})).json()["access_token"]
            as_system = {"Authorization": f"Bearer {token}"}
            assert DNI not in (await client.get(f"/v1/cases/{case_id}/result", headers=as_system)).text
            for _ in range(2):
                assert DNI in (await client.get(f"/v1/cases/{case_id}/result", headers=as_system, params={"reveal": "true"})).text

        with tenancy.acting_for(scratch_unit):
            async with factory() as session:
                log = (await session.scalars(select(DataAccess).where(DataAccess.case_id == case_id).order_by(DataAccess.created_at))).all()
                assert [(e.action, e.channel, e.role) for e in log] == [("ver_datos", "web", "operador"), ("ver_datos", "api", "integracion"), ("ver_datos", "api", "integracion")]
                assert log[0].reason == "revisar el ingreso" and log[0].actor.startswith("test-datos-operador")
                assert await session.scalar(select(func.count()).select_from(DataAccess).where(DataAccess.reason.contains(DNI))) == 0
    finally:
        with tenancy.acting_for(scratch_unit):
            async with factory() as session:
                systems = list((await session.scalars(select(ApiClient.user_id))).all())
                await session.execute(delete(ApiClient))
                await session.execute(delete(User).where(User.id.in_(systems) | User.email.like(f"test-datos-%-{scratch_unit}@example.com")))
                await session.commit()
        store.delete(key) if hasattr(store, "delete") else None


async def _admin(client: AsyncClient, factory, unit: str) -> dict[str, str]:
    email = f"test-datos-admin-{unit}@example.com"
    async with factory() as session:
        await UserRepository(session).create(name="Datos admin", email=email, password_hash=hash_password(_PASSWORD), role="admin", tenant=unit)
        await session.commit()
    r = await client.post("/auth/login", json={"email": email, "password": _PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
