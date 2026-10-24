"""Deleting (VRT-72) against the real API, Postgres and MinIO. What nothing
needs goes for good, files included; what history names is archived; a
file another row still uses stays; the technical records go after their term."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.domain.document_type_catalog import DocumentTypeDefinition
from idp.domain.process_profile_seed import convenios_definition
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import (
    A2ATask,
    BulkJob,
    CalibrationVersion,
    Case,
    CaseRun,
    DataAccess,
    Document,
    DocumentTypeRecord,
    DocumentTypeSuggestion,
    DocumentTypeVersion,
    EvalCase,
    EvalSuite,
    LensRecord,
    OutboxEvent,
    AuditLogEntry,
    ReviewItem,
    ProcessProfile,
    ProcessProfileVersion,
    Tenant,
    UploadedFile,
    UploadSession,
    User,
    ValidationRuleDefinition,
)
from idp.persistence.repositories import UserRepository, register_tenant
from idp.pipeline.deletion import housekeep
from idp.storage.object_store import S3ObjectStore

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]
_PASSWORD = "test-password-borrado"


def _gone(store: S3ObjectStore, key: str) -> bool:
    try:
        store.get(key)
    except Exception:
        return True
    return False


async def _profile(session, key: str | None = None) -> ProcessProfileVersion:
    definition = convenios_definition()
    profile = ProcessProfile(key=key or f"del-{uuid.uuid4().hex[:6]}", name="Borrado")
    profile.versions.append(ProcessProfileVersion(version=1, status="published", definition=definition.model_dump(mode="json"),
                                                  content_hash=definition.content_hash(), semantic_catalog_version=1, created_by="test"))
    session.add(profile)
    await session.flush()
    return profile.versions[0]


async def _case(session, store, unit: str, version_id: uuid.UUID, *, files: int = 1, **fields) -> tuple[Case, list[Document]]:
    case = Case(status="completed", profile_version_id=version_id, verdict="continue", **fields)
    session.add(case)
    await session.flush()
    documents = []
    for i in range(files):
        key = f"{unit}/{case.id}/doc{i}.png"
        store.put(key, b"imagen", content_type="image/png")
        store.put(f"{key}.parsed.json", b"{}", content_type="application/json")
        documents.append(Document(case_id=case.id, status="completed", document_type="payslip", storage_key=key, original_filename=f"doc{i}.png"))
    session.add_all(documents)
    await session.flush()
    return case, documents


@asynccontextmanager
async def _client(settings, unit: str):
    """An admin who is also of the platform team, and an operador, of ``unit``."""
    factory = get_session_factory(settings)
    with tenancy.acting_for(unit):
        async with factory() as session:
            users = UserRepository(session)
            admin = await users.create(name="Del admin", email=f"test-del-admin-{unit}@example.com", password_hash=hash_password(_PASSWORD), role="admin")
            admin.platform_role = "admin"
            await users.create(name="Del op", email=f"test-del-operador-{unit}@example.com", password_hash=hash_password(_PASSWORD), role="operador")
            await session.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            headers = {}
            for role in ("admin", "operador"):
                r = await client.post("/auth/login", json={"email": f"test-del-{role}-{unit}@example.com", "password": _PASSWORD})
                headers[role] = {"Authorization": f"Bearer {r.json()['access_token']}"}
            yield client, headers["admin"], headers["operador"]
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.email.like(f"test-del-%-{unit}@example.com")))
            await session.commit()


@pytest.mark.asyncio
async def test_a_case_a_document_and_a_bulk_job_are_deleted_with_their_files(live_settings, scratch_unit):
    factory, store = get_session_factory(live_settings), S3ObjectStore(live_settings)
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            version = await _profile(session)
            case, (doc,) = await _case(session, store, scratch_unit, version.id)
            two, (kept, removed) = await _case(session, store, scratch_unit, version.id, files=2)
            busy, _ = await _case(session, store, scratch_unit, version.id)
            session.add(CaseRun(case_id=busy.id, run_number=1, trigger="submit", status="running"))
            suite = EvalSuite(name="dorado", source="corrections", created_by="test")
            suite.cases.append(EvalCase(position=0, filename="doc0.png", storage_key=doc.storage_key, source_document_id=doc.id, expected_fields={}))
            session.add(suite)
            job = BulkJob(name="lote", archive_sha256="0" * 64, created_by="test")
            session.add(job)
            await session.flush()
            in_job, (job_doc,) = await _case(session, store, scratch_unit, version.id, bulk_job_id=job.id)
            await session.commit()
            ids = {"case": case.id, "doc": doc.storage_key, "two": two.id, "kept": kept.storage_key, "removed": removed.id, "removed_key": removed.storage_key,
                   "busy": busy.id, "suite": suite.id, "job": job.id, "in_job": in_job.id, "job_key": job_doc.storage_key}

    async with _client(live_settings, scratch_unit) as (client, admin, operador):
        reason = {"reason": "Se subió por error, era de otro cliente"}
        assert (await client.request("DELETE", f"/v1/cases/{ids['case']}", headers=operador, json=reason)).status_code == 403, "only an admin"
        assert (await client.request("DELETE", f"/v1/cases/{ids['busy']}", headers=admin, json=reason)).status_code == 409, "not while it runs"
        assert (await client.request("DELETE", f"/v1/cases/{ids['case']}", headers=admin, json=reason)).status_code == 204
        assert (await client.get(f"/v1/cases/{ids['case']}", headers=admin)).status_code == 404

        assert (await client.delete(f"/documents/{ids['removed']}", headers=operador)).status_code == 403
        assert (await client.delete(f"/documents/{ids['removed']}", headers=admin)).status_code == 204
        assert (await client.delete(f"/v1/bulk-jobs/{ids['job']}", headers=admin)).status_code == 204

    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            assert await session.get(Case, ids["case"]) is None and await session.get(EvalSuite, ids["suite"]) is not None
            assert await session.scalar(select(EvalCase.id).where(EvalCase.suite_id == ids["suite"])) is None, "the golden copy of its data went with it"
            assert _gone(store, ids["doc"]) and _gone(store, f"{ids['doc']}.parsed.json")
            log = (await session.scalars(select(DataAccess).where(DataAccess.case_id == ids["case"]))).one()
            assert (log.action, log.reason, log.role) == ("eliminar", reason["reason"], "admin")

            assert await session.get(Document, ids["removed"]) is None and _gone(store, ids["removed_key"])
            assert not _gone(store, ids["kept"]), "the other document of the case stays"
            run = await session.scalar(select(CaseRun).where(CaseRun.case_id == ids["two"], CaseRun.trigger == "document_removed"))
            assert run is not None, "the case is re-evaluated without it"

            assert await session.get(BulkJob, ids["job"]) is None and await session.get(Case, ids["in_job"]) is None and _gone(store, ids["job_key"])
            assert await session.get(Case, ids["busy"]) is not None


@pytest.mark.asyncio
async def test_what_nothing_used_goes_and_what_was_used_is_archived(live_settings, scratch_unit):
    factory, store = get_session_factory(live_settings), S3ObjectStore(live_settings)
    type_key = f"del_tipo_{uuid.uuid4().hex[:6]}"
    used_type = f"{type_key}_usado"
    rule_ids = [f"del.regla.{uuid.uuid4().hex[:6]}", f"del.regla.{uuid.uuid4().hex[:6]}"]
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            unused, used = await _profile(session), await _profile(session)
            await _profile(session, key="ad-hoc")
            unused.profile.versions.append(ProcessProfileVersion(version=2, status="draft", definition=unused.definition, content_hash="x",
                                                                 semantic_catalog_version=1))
            await _case(session, store, scratch_unit, used.id)
            for key in (type_key, used_type):
                definition = DocumentTypeDefinition.model_validate({"key": key, "display_name": key, "schema_title": "Prueba", "description": "prueba", "fields": [
                    {"name": "monto", "type": "float", "description": "m"}]})
                record = DocumentTypeRecord(key=key)
                record.versions.append(DocumentTypeVersion(version=1, status="published", definition=definition.model_dump(mode="json"),
                                                           content_hash=definition.content_hash()))
                session.add(record)
            _, (doc,) = await _case(session, store, scratch_unit, used.id)
            doc.document_type = used_type
            session.add_all([ValidationRuleDefinition(rule_id=rule_ids[0], kind="cel", status="draft", description_nl="borrador", category="self"),
                             ValidationRuleDefinition(rule_id=rule_ids[1], kind="cel", status="active", description_nl="activa", category="self")])
            await session.commit()
            keys = {"unused": unused.profile.key, "used": used.profile.key}
            rules = {r.rule_id: r.id for r in (await session.scalars(select(ValidationRuleDefinition).where(ValidationRuleDefinition.rule_id.in_(rule_ids)))).all()}
    try:
        async with _client(live_settings, scratch_unit) as (client, admin, operador):
            assert (await client.delete(f"/v1/profiles/{keys['unused']}/versions/1", headers=admin)).status_code == 409, "a published version is retired"
            assert (await client.delete(f"/v1/profiles/{keys['unused']}/versions/2", headers=admin)).status_code == 204
            assert (await client.delete(f"/v1/profiles/{keys['unused']}", headers=operador)).status_code == 403
            assert (await client.delete(f"/v1/profiles/{keys['unused']}", headers=admin)).json() == {"outcome": "deleted"}
            assert (await client.delete(f"/v1/profiles/{keys['used']}", headers=admin)).json() == {"outcome": "archived"}
            assert (await client.delete("/v1/profiles/ad-hoc", headers=admin)).status_code == 409
            profiles = {p["key"]: p for p in (await client.get("/v1/profiles", headers=admin)).json()}
            assert keys["unused"] not in profiles and profiles[keys["used"]]["active_version"] is None

            assert (await client.delete(f"/v1/document-types/{type_key}", headers=admin)).json() == {"outcome": "deleted"}
            assert (await client.delete(f"/v1/document-types/{used_type}", headers=admin)).json() == {"outcome": "archived"}
            types = {t["key"]: t for t in (await client.get("/v1/document-types", headers=admin)).json()}
            assert type_key not in types and types[used_type]["active_version"] is None

            assert (await client.delete(f"/validation-rules/{rules[rule_ids[1]]}", headers=admin)).status_code == 409, "an applied rule is disabled"
            assert (await client.delete(f"/validation-rules/{rules[rule_ids[0]]}", headers=admin)).status_code == 204

            lens = (await client.get("/v1/lenses", headers=admin)).json()[0]
            assert (await client.delete(f"/v1/lenses/{lens['key']}", headers=admin)).status_code == 204
            assert lens["key"] not in {x["key"] for x in (await client.get("/v1/lenses", headers=admin)).json()}
            assert (await client.put(f"/v1/lenses/{lens['key']}", headers=admin, json=lens)).status_code == 200, "saving it brings it back"
            assert lens["key"] in {x["key"] for x in (await client.get("/v1/lenses", headers=admin)).json()}

            people = {p["email"]: p["id"] for p in (await client.get("/users", headers=admin)).json()}
            me, other = people[f"test-del-admin-{scratch_unit}@example.com"], people[f"test-del-operador-{scratch_unit}@example.com"]
            assert (await client.delete(f"/users/{me}", headers=admin)).status_code == 409
            assert (await client.delete(f"/users/{other}", headers=admin)).status_code == 204
            assert other not in {p["id"] for p in (await client.get("/users", headers=admin)).json()}
    finally:
        async with factory() as session:
            await session.execute(delete(DocumentTypeRecord).where(DocumentTypeRecord.key.in_([type_key, used_type])))
            await session.execute(delete(ValidationRuleDefinition).where(ValidationRuleDefinition.rule_id.in_(rule_ids)))
            await session.execute(delete(LensRecord).where(LensRecord.archived_at.is_not(None)))
            await session.commit()


@pytest.mark.asyncio
async def test_only_a_unit_without_cases_is_deleted(live_settings, scratch_unit, other_unit):
    factory, store = get_session_factory(live_settings), S3ObjectStore(live_settings)
    empty = f"del-{uuid.uuid4().hex[:8]}"
    async with factory() as session:
        await register_tenant(session, empty, "Vacía", examples=True)
    with tenancy.acting_for(other_unit):
        async with factory() as session:
            await _case(session, store, other_unit, (await _profile(session)).id)
            await session.commit()
    async with _client(live_settings, scratch_unit) as (client, admin, _):
        assert (await client.delete(f"/v1/tenants/{scratch_unit}", headers=admin)).status_code == 409, "not the one you work in"
        assert (await client.delete(f"/v1/tenants/{other_unit}", headers=admin)).status_code == 409, "it has cases"
        assert (await client.delete(f"/v1/tenants/{empty}", headers=admin)).status_code == 204
    async with factory() as session:
        assert await session.get(Tenant, empty) is None
        with tenancy.acting_for(empty):
            assert await session.scalar(select(ProcessProfile.id).limit(1)) is None, "its processes went with it"


@pytest.mark.asyncio
async def test_technical_records_go_after_their_term_and_a_file_in_use_stays(live_settings, scratch_unit):
    factory, store = get_session_factory(live_settings), S3ObjectStore(live_settings)
    old = datetime.now(UTC) - timedelta(days=live_settings.technical_retention_days + 1)
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            version = await _profile(session)
            case, (doc,) = await _case(session, store, scratch_unit, version.id)
            rejected = f"{scratch_unit}/sesion/rechazado.png"
            store.put(rejected, b"x", content_type="image/png")
            upload = UploadSession(token_hash="0" * 64, profile_version_id=version.id, status="submitted", expires_at=old, created_by="t", created_at=old,
                                   submitted_case_id=case.id)
            for name, key, verdict in (("bueno.png", doc.storage_key, "ok"), ("malo.png", rejected, "reject")):
                upload.files.append(UploadedFile(filename=name, content_type="image/png", size=1, storage_key=key, checks=[], verdict=verdict))
            fresh = OutboxEvent(type="pe.veritium.case.run.completed", data={}, dispatched_at=old)
            session.add_all([
                upload, fresh,
                OutboxEvent(type="pe.veritium.case.run.completed", data={}, created_at=old, dispatched_at=old),
                A2ATask(id=f"t-{uuid.uuid4().hex}", context_id="c", owner="o", state="TASK_STATE_COMPLETED", snapshot={}, created_at=old, updated_at=old),
                A2ATask(id=f"t-{uuid.uuid4().hex}", context_id="c", owner="o", state="TASK_STATE_INPUT_REQUIRED", snapshot={}, created_at=old, updated_at=old),
            ])
            await session.commit()
            upload_id, fresh_id = upload.id, fresh.id

    assert await housekeep(live_settings) >= 3
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            assert await session.get(UploadSession, upload_id) is None
            assert _gone(store, rejected) and not _gone(store, doc.storage_key), "the file that became a document stays"
            assert await session.get(OutboxEvent, fresh_id) is not None
            assert (await session.scalars(select(A2ATask.state))).all() == ["TASK_STATE_INPUT_REQUIRED"], "an unfinished task waits"


@pytest.mark.asyncio
async def test_a_suite_a_suggestion_and_a_calibration_draft_are_deleted(live_settings, scratch_unit):
    factory, store = get_session_factory(live_settings), S3ObjectStore(live_settings)
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            case, (doc,) = await _case(session, store, scratch_unit, (await _profile(session)).id)
            own = f"{scratch_unit}/suite/propio.png"
            store.put(own, b"x", content_type="image/png")
            suite = EvalSuite(name="tabla", source="table", created_by="test")
            suite.cases.extend([EvalCase(position=0, filename="propio.png", storage_key=own, expected_fields={}),
                                EvalCase(position=1, filename="doc0.png", storage_key=doc.storage_key, expected_fields={})])
            suggestions = [DocumentTypeSuggestion(document_id=doc.id, case_id=case.id, suggested_type_name="t", suggested_display_name="T", rationale="r",
                                                  fields=[], status=s) for s in ("pending", "rejected")]
            calibrations = [CalibrationVersion(version=v, status=s, model={}, report={}, created_by="t") for v, s in ((1, "active"), (2, "draft"))]
            session.add_all([suite, *suggestions, *calibrations])
            await session.commit()
            suite_id, pending, rejected = suite.id, suggestions[0].id, suggestions[1].id

    async with _client(live_settings, scratch_unit) as (client, admin, _):
        assert (await client.delete(f"/v1/eval-suites/{suite_id}", headers=admin)).status_code == 204
        for suggestion in (pending, rejected):
            assert (await client.delete(f"/type-suggestions/{suggestion}", headers=admin)).status_code == 204
        assert (await client.delete("/v1/calibration/1", headers=admin)).status_code == 409, "runs name it"
        assert (await client.delete("/v1/calibration/2", headers=admin)).status_code == 204

    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            assert await session.get(EvalSuite, suite_id) is None and await session.get(DocumentTypeSuggestion, pending) is None
            assert _gone(store, own) and not _gone(store, doc.storage_key), "the case's document still uses its file"
            assert [c.version for c in (await session.scalars(select(CalibrationVersion))).all()] == [1]


@pytest.mark.asyncio
async def test_an_observation_is_dismissed_without_seeing_the_data(live_settings, scratch_unit):
    factory, store = get_session_factory(live_settings), S3ObjectStore(live_settings)
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            _, (doc,) = await _case(session, store, scratch_unit, (await _profile(session)).id)
            doc.status = "needs_review"
            item = ReviewItem(document_id=doc.id, field_path="employee_code", current_value={"value": "42285866"}, confidence=1.0, reason="validation_issue")
            session.add(item)
            await session.commit()
            item_id, doc_id = item.id, doc.id
    async with _client(live_settings, scratch_unit) as (client, _, operador):
        assert (await client.post(f"/review/{item_id}/dismiss", headers=operador, json={"justification": "x"})).status_code == 422, "it needs a reason"
        done = await client.post(f"/review/{item_id}/dismiss", headers=operador, json={"justification": "El maestro de empleados está desactualizado"})
        assert done.status_code == 200 and done.json()["status"] == "dismissed"
        assert (await client.post(f"/review/{item_id}/dismiss", headers=operador, json={"justification": "otra vez"})).status_code == 409
        assert item_id not in {i["id"] for i in (await client.get("/review", headers=operador)).json()}
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            entry = await session.scalar(select(AuditLogEntry).where(AuditLogEntry.review_item_id == item_id))
            assert entry.reason_code == "dismissed" and entry.corrected_value == {"value": "42285866"}, "the value stays as it was"
            assert (await session.get(Document, doc_id)).status == "completed"
