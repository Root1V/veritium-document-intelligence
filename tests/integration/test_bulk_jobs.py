"""Bulk jobs against the real API, Postgres and MinIO (VRT-48), without an
LLM: a ZIP with one folder per case becomes cases in the bulk lane, queued;
the feeder releases them one at a time; when none is left the job finishes
and says so; the results come out one row per case."""

from __future__ import annotations

import asyncio
import io
import uuid
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.config import Settings
from idp.persistence.db import get_session_factory
from idp.persistence.models import BulkJob, Case, CaseRun, OutboxEvent
from idp.persistence.repositories import UserRepository
from idp.pipeline import bulk, orchestrator

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

_OPERATOR, _PASSWORD = "test-operador-masivo@example.com", "test-password-masivo"


def _zip(**extra: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifiesto.csv", "expediente;perfil;nacionalidad\nEXP-A;convenios;PE\nEXP-Z;convenios;PE\n")
        zf.writestr("EXP-A/solicitud.pdf", b"%PDF-1.4 a")
        zf.writestr("EXP-A/boleta.png", b"png")
        zf.writestr("EXP-B/boleta.pdf", b"%PDF-1.4 b")
        zf.writestr("EXP-B/notas.txt", b"x")
        zf.writestr("suelto.pdf", b"%PDF-1.4 c")
        for name, content in extra.items():
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.fixture
def no_pipeline(monkeypatch):
    async def nothing(*, session, document_id, document_repo, **_):
        await document_repo.set_status(document_id, "failed")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", nothing)


async def _drain() -> None:
    while bulk._tasks:
        await asyncio.gather(*list(bulk._tasks))


@pytest.mark.asyncio
async def test_a_bulk_job_runs_its_cases_a_few_at_a_time(live_settings, no_pipeline):
    settings = Settings(case_executor="in_process", bulk_max_in_flight=1)
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_OPERATOR) is None:
            await users.create(name="Operador Masivo", email=_OPERATOR, password_hash=hash_password(_PASSWORD), role="operador")
            await session.commit()

    job_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            jwt = {"Authorization": f"Bearer {(await client.post('/auth/login', json={'email': _OPERATOR, 'password': _PASSWORD})).json()['access_token']}"}
            key = {**jwt, "Idempotency-Key": f"test-masivo-{uuid.uuid4().hex[:8]}"}
            sent = await client.post("/v1/bulk-jobs", headers=key, data={"profile": "convenios", "name": "prueba"}, files={"archive": ("lote.zip", _zip(), "application/zip")})
            assert sent.status_code == 202, sent.text
            job_id = sent.json()["id"]
            assert sent.json()["cases"] == 2
            assert sorted(str(s["reference"]) for s in sent.json()["skipped"]) == ["EXP-B", "EXP-Z", "None"]

            again = await client.post("/v1/bulk-jobs", headers=key, files={"archive": ("lote.zip", _zip(), "application/zip")})
            assert again.json()["id"] == job_id and again.json()["replayed"]
            other = await client.post("/v1/bulk-jobs", headers=key, files={"archive": ("lote.zip", _zip(**{"EXP-C/a.pdf": b"c"}), "application/zip")})
            assert other.status_code == 422
            assert (await client.post("/v1/bulk-jobs", headers=jwt, files={"archive": ("x.zip", b"no zip", "application/zip")})).status_code == 422

            detail = (await client.get(f"/v1/bulk-jobs/{job_id}", headers=jwt)).json()
            assert [(i["external_ref"], i["outcome"], i["progress"]["current"]) for i in detail["items"]] == [("EXP-A", "pending", "En cola"), ("EXP-B", "pending", "En cola")]

            async with factory() as session:
                cases = (await session.scalars(select(Case).where(Case.bulk_job_id == uuid.UUID(job_id)).order_by(Case.external_ref))).all()
                assert [(c.channel, c.request_input_payload) for c in cases] == [("bulk", {"nacionalidad": "PE"}), ("bulk", None)]

            assert await bulk.release(settings) == 1, "one at a time"
            assert await bulk.finish(settings) == 0
            await _drain()
            assert await bulk.release(settings) == 1
            await _drain()
            assert await bulk.release(settings) == 0
            assert await bulk.finish(settings) == 1

            detail = (await client.get(f"/v1/bulk-jobs/{job_id}", headers=jwt)).json()
            assert detail["finished_at"] and "pending" not in detail["outcomes"] and sum(detail["outcomes"].values()) == 2
            results = (await client.get(f"/v1/bulk-jobs/{job_id}/results", headers=jwt)).text
            assert results.splitlines()[0] == "﻿expediente,perfil,resultado,motivos,id" and "EXP-A,convenios" in results and "EXP-Z,,Expediente no procesado" in results
            template = (await client.get("/v1/bulk-jobs/template", params={"profile": "convenios"}, headers=jwt)).text
            assert template.splitlines()[0] == "﻿expediente,perfil,nacionalidad"

        async with factory() as session:
            event = (await session.scalars(select(OutboxEvent).where(OutboxEvent.subject == job_id))).one()
            assert event.type == "pe.veritium.bulk_job.completed" and event.data["cases"] == 2
    finally:
        async with factory() as session:
            if job_id:
                ids = list((await session.scalars(select(Case.id).where(Case.bulk_job_id == uuid.UUID(job_id)))).all())
                await session.execute(delete(OutboxEvent).where(OutboxEvent.subject.in_([job_id, *map(str, ids)])))
                await session.execute(delete(CaseRun).where(CaseRun.case_id.in_(ids)))
                await session.execute(delete(Case).where(Case.id.in_(ids)))
                await session.execute(delete(BulkJob).where(BulkJob.id == uuid.UUID(job_id)))
            await session.commit()
