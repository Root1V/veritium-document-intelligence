"""Events in and out against Redpanda, Postgres and MinIO (VRT-49), without
an LLM: a command on the bus names its documents by claim-check; Veritium
creates the case and answers on the bus; a replay is answered the same
without a second case; a command it cannot take is answered with why. The
same command over HTTP (POST /v1/events) behaves alike."""

from __future__ import annotations

import asyncio
import json
import socket
import uuid

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from idp.api.app import create_app
from idp.api.deps import get_app_settings
from idp.auth.security import hash_password
from idp.config import Settings
from idp.events import bus
from idp.execution import handover
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, CaseRun, OutboxEvent
from idp.persistence.repositories import UserRepository
from idp.pipeline import orchestrator
from idp.storage.object_store import S3ObjectStore

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]

BROKERS = "localhost:19092"
_OPERATOR, _PASSWORD = "test-integracion-eventos@example.com", "test-password-eventos"


@pytest.fixture
def require_redpanda():
    try:
        socket.create_connection(("localhost", 19092), timeout=1).close()
    except OSError:
        pytest.skip("Redpanda no alcanzable en localhost:19092 (docker compose up -d redpanda)")


@pytest.fixture
def no_pipeline(monkeypatch):
    async def nothing(*, session, document_id, document_repo, **_):
        await document_repo.set_status(document_id, "failed")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", nothing)


def _command(type_: str, data: dict) -> dict:
    return {"specversion": "1.0", "id": uuid.uuid4().hex, "source": "test/core", "type": type_, "data": data}


async def _answers(topic: str, ids: set[str], timeout: float = 30.0) -> dict[str, dict]:
    consumer = AIOKafkaConsumer(topic, bootstrap_servers=BROKERS, auto_offset_reset="earliest", group_id=None)
    await consumer.start()
    found: dict[str, dict] = {}
    try:
        async with asyncio.timeout(timeout):
            while ids - found.keys():
                for records in (await consumer.getmany(timeout_ms=500)).values():
                    for r in records:
                        event = json.loads(r.value)
                        if event["data"].get("command_id") in ids:
                            assert dict(r.headers)["content-type"].startswith(b"application/cloudevents+json")
                            found[event["data"]["command_id"]] = event
    finally:
        await consumer.stop()
    return found


@pytest.mark.asyncio
async def test_commands_in_answers_out(live_settings, require_redpanda, no_pipeline):
    run_id = uuid.uuid4().hex[:8]
    prefix = f"inbox-test/{run_id}/"
    settings = Settings(
        case_executor="in_process", event_bus_brokers=BROKERS, event_bus_in_topic=f"test.in.{run_id}", event_bus_out_topic=f"test.out.{run_id}",
        claim_check_allowed_prefixes=[f"s3://{live_settings.storage_bucket}/{prefix}"], event_bus_publish_interval_seconds=0.2,
    )
    store = S3ObjectStore(live_settings)
    store.put(f"{prefix}boleta.pdf", b"%PDF-1.4 boleta", content_type="application/pdf")
    ok = _command("pe.veritium.case.submit", {
        "profile": "convenios", "external_ref": f"EV-{run_id}", "process_data": {"nacionalidad": "PE"},
        "documents": [{"url": f"s3://{live_settings.storage_bucket}/{prefix}boleta.pdf"}],
    })
    outside = _command("pe.veritium.case.submit", {"profile": "convenios", "documents": [{"url": "https://ejemplo.com/a.pdf"}]})
    unknown = _command("pe.veritium.case.submit", {"profile": "no-existe", "documents": [{"url": f"s3://{live_settings.storage_bucket}/{prefix}boleta.pdf"}]})

    stop = asyncio.Event()
    task = asyncio.create_task(bus.run(settings, stop))
    producer = AIOKafkaProducer(bootstrap_servers=BROKERS)
    await producer.start()
    try:
        for command in (ok, outside, unknown, ok):  # the last one: a replay
            await producer.send_and_wait(settings.event_bus_in_topic, json.dumps(command).encode(), headers=[("content-type", bus.CONTENT_TYPE)])
        answers = await _answers(settings.event_bus_out_topic, {ok["id"], outside["id"], unknown["id"]})
        while handover.tasks:
            await asyncio.gather(*list(handover.tasks))

        accepted = answers[ok["id"]]
        assert accepted["type"] == "pe.veritium.command.accepted" and accepted["data"]["external_ref"] == f"EV-{run_id}"
        assert accepted["subject"] == accepted["data"]["case_id"], "keyed by case: its events stay in order"
        assert answers[outside["id"]]["type"] == "pe.veritium.command.rejected" and "origen permitido" in answers[outside["id"]]["data"]["reason"]
        assert "no-existe" in answers[unknown["id"]]["data"]["reason"]

        factory = get_session_factory(live_settings)
        async with factory() as session:
            cases = (await session.scalars(select(Case).where(Case.external_ref == f"EV-{run_id}").options(selectinload(Case.documents)))).all()
            assert len(cases) == 1, "the replay did not create a second case"
            case_id = cases[0].id
            assert [d.original_filename for d in cases[0].documents] == ["boleta.pdf"]

        # The same commands over HTTP.
        async with factory() as session:
            users = UserRepository(session)
            if await users.get_by_email(_OPERATOR) is None:
                await users.create(name="Integración Eventos", email=_OPERATOR, password_hash=hash_password(_PASSWORD), role="integracion")
                await session.commit()
        app = create_app()
        app.dependency_overrides[get_app_settings] = lambda: settings
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            jwt = {"Authorization": f"Bearer {(await client.post('/auth/login', json={'email': _OPERATOR, 'password': _PASSWORD})).json()['access_token']}"}
            replay = await client.post("/v1/events", headers={**jwt, "Content-Type": "application/cloudevents+json"}, content=json.dumps(ok))
            assert replay.status_code == 202 and replay.json()["replayed"] and replay.json()["case_id"] == str(case_id)
            add = _command("pe.veritium.case.documents.add", {"external_ref": f"EV-{run_id}", "documents": [{"url": f"s3://{live_settings.storage_bucket}/{prefix}boleta.pdf", "filename": "boleta-2.pdf"}]})
            binary_headers = {**jwt, "ce-specversion": "1.0", "ce-id": add["id"], "ce-source": add["source"], "ce-type": add["type"], "Content-Type": "application/json"}
            added = await client.post("/v1/events", headers=binary_headers, content=json.dumps(add["data"]))
            assert added.status_code == 202 and added.json()["run_number"] == 2, added.text
            refused = await client.post("/v1/events", headers={**jwt, "Content-Type": "application/cloudevents+json"}, content=json.dumps(outside))
            assert refused.status_code == 422 and "origen permitido" in refused.json()["detail"]
            assert (await client.post("/v1/events", headers={**jwt, "Content-Type": "application/cloudevents+json"}, content=b"{}")).status_code == 400
            while handover.tasks:
                await asyncio.gather(*list(handover.tasks))
    finally:
        stop.set()
        await task
        await producer.stop()
        admin = AIOKafkaAdminClient(bootstrap_servers=BROKERS)
        await admin.start()
        await admin.delete_topics([settings.event_bus_in_topic, settings.event_bus_out_topic])
        await admin.close()
        async with get_session_factory(live_settings)() as session:
            ids = list((await session.scalars(select(Case.id).where(Case.external_ref == f"EV-{run_id}"))).all())
            commands = [ok["id"], outside["id"], unknown["id"]]
            await session.execute(delete(OutboxEvent).where(OutboxEvent.subject.in_([*map(str, ids), *commands]) | OutboxEvent.data["command_id"].astext.in_(commands)))
            await session.execute(delete(CaseRun).where(CaseRun.case_id.in_(ids)))
            await session.execute(delete(Case).where(Case.id.in_(ids)))
            await session.commit()
