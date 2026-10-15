"""Removing a case's personal data (VRT-58) against the real API, Postgres
and MinIO: an admin suppresses it on request, or the process's retention
term runs out. Files, what was read and extracted, and the texts that quote
the data go; the case stays, anonymized, with its verdict's kinds; it is
recorded, and the case is not processed again."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.domain.process_profile_seed import convenios_definition
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import (
    AuditLogEntry,
    Case,
    DataAccess,
    Document,
    Extraction,
    ProcessProfile,
    ProcessProfileVersion,
    ReviewItem,
    User,
    ValidationIssue,
)
from idp.persistence.repositories import UserRepository
from idp.pipeline import retention
from idp.storage.object_store import S3ObjectStore

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]
_PASSWORD = "test-password-retencion"
DNI = "42285866"


async def _profile(session, days: int | None) -> uuid.UUID:
    definition = convenios_definition().model_copy(update={"retention_days": days})
    profile = ProcessProfile(key=f"ret-{uuid.uuid4().hex[:6]}", name="Retención")
    profile.versions.append(ProcessProfileVersion(version=1, status="published", definition=definition.model_dump(mode="json"),
                                                  content_hash=definition.content_hash(), semantic_catalog_version=1, created_by="test"))
    session.add(profile)
    await session.flush()
    return profile.versions[0].id


async def _case(session, store, unit: str, version_id: uuid.UUID, *, decided: datetime) -> tuple[uuid.UUID, str]:
    case = Case(status="completed", profile_version_id=version_id, verdict="human_review", verdict_at=decided, request_input_payload={"dni": DNI},
                verdict_reasons=[{"kind": "rule", "decision": "human_review", "ref": {"rule_id": "r"}, "message": f"El DNI {DNI} no coincide"}])
    session.add(case)
    await session.flush()
    key = f"{unit}/{case.id}/boleta.png"
    store.put(key, b"imagen", content_type="image/png")
    store.put(f"{key}.parsed.json", b"{}", content_type="application/json")
    doc = Document(case_id=case.id, status="needs_review", document_type="payslip", storage_key=key, original_filename=f"boleta-{DNI}.png")
    session.add(doc)
    await session.flush()
    item = ReviewItem(document_id=doc.id, field_path="employee_code", current_value={"value": DNI}, confidence=0.4, reason="low_confidence", status="corrected")
    session.add_all([
        Extraction(document_id=doc.id, schema_version="1", payload={"employee_code": {"value": DNI}}, parser_backend="rapidocr", extraction_method="agentic"),
        ValidationIssue(case_id=case.id, document_id=doc.id, rule_id="r", category="self", severity="warning", message=f"DNI {DNI}", confidence=1,
                        confidence_method="rule", explanation=DNI, expected={"value": DNI}),
        item,
    ])
    await session.flush()
    session.add(AuditLogEntry(review_item_id=item.id, reviewer_identity="x", original_value={"value": DNI}, corrected_value={"value": DNI}, original_confidence=0.4,
                              justification=f"era {DNI}"))
    return case.id, key


@pytest.mark.asyncio
async def test_a_case_is_suppressed_on_request_and_others_expire_by_their_term(live_settings, scratch_unit):
    factory, store = get_session_factory(live_settings), S3ObjectStore(live_settings)
    now = datetime.now(UTC)
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            kept_forever, short = await _profile(session, None), await _profile(session, 30)
            suppressed, suppressed_key = await _case(session, store, scratch_unit, kept_forever, decided=now)
            expired, expired_key = await _case(session, store, scratch_unit, short, decided=now - timedelta(days=31))
            recent, _ = await _case(session, store, scratch_unit, short, decided=now - timedelta(days=5))
            untouched, _ = await _case(session, store, scratch_unit, kept_forever, decided=now - timedelta(days=4000))
            users = UserRepository(session)
            for role in ("admin", "operador"):
                await users.create(name=f"Ret {role}", email=f"test-ret-{role}-{scratch_unit}@example.com", password_hash=hash_password(_PASSWORD), role=role)
            await session.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            async def login(role: str) -> dict[str, str]:
                r = await client.post("/auth/login", json={"email": f"test-ret-{role}-{scratch_unit}@example.com", "password": _PASSWORD})
                return {"Authorization": f"Bearer {r.json()['access_token']}"}

            admin, operador = await login("admin"), await login("operador")
            body = {"reason": "Solicitud de cancelación del titular (carta 123)"}
            assert (await client.post(f"/v1/cases/{suppressed}/suppress", headers=operador, json=body)).status_code == 403, "only an admin removes data"
            done = await client.post(f"/v1/cases/{suppressed}/suppress", headers=admin, json=body)
            assert done.status_code == 200 and done.json()["files_removed"] == 2
            again = await client.post(f"/v1/cases/{suppressed}/suppress", headers=admin, json=body)
            assert again.status_code == 200 and again.json()["files_removed"] == 0, "idempotent"

            # Not processed again, and nothing of the data shows, even to whoever may see them.
            assert (await client.post(f"/v1/cases/{suppressed}/reprocess", headers=operador, json={"kind": "case"})).status_code == 409
            summary = (await client.get(f"/v1/cases/{suppressed}", headers=operador)).json()
            assert summary["personal_data"]["removed_reason"] == "suprimido" and summary["personal_data"]["can_reveal"] is False
            result = await client.get(f"/v1/cases/{suppressed}/result", headers=operador, params={"reveal": "true"})
            assert DNI not in result.text and result.json()["verdict"]["reasons"][0]["kind"] == "rule"

        assert await retention.expire(live_settings) >= 1

        with tenancy.acting_for(scratch_unit):
            async with factory() as session:
                for case_id, key, reason in ((suppressed, suppressed_key, "suprimido"), (expired, expired_key, "vencido")):
                    case = await session.get(Case, case_id)
                    assert case.anonymized_reason == reason and case.request_input_payload is None and case.verdict == "human_review"
                    for k in (key, f"{key}.parsed.json"):
                        with pytest.raises(Exception):
                            store.get(k)
                    assert await session.scalar(select(Extraction.id).join(Document).where(Document.case_id == case_id)) is None
                    texts = [*(await session.execute(select(ValidationIssue.message, ValidationIssue.explanation).where(ValidationIssue.case_id == case_id))).all(),
                             *(await session.execute(select(AuditLogEntry.justification, Document.original_filename).join(ReviewItem, ReviewItem.id == AuditLogEntry.review_item_id)
                                                     .join(Document, Document.id == ReviewItem.document_id).where(Document.case_id == case_id))).all()]
                    assert texts and not [t for row in texts for t in row if t and DNI in t]
                for case_id in (recent, untouched):
                    assert (await session.get(Case, case_id)).anonymized_at is None, "within its term, or a process that keeps"
                log = {(e.case_id, e.action): e for e in (await session.scalars(select(DataAccess))).all()}
                assert log[(suppressed, "suprimir")].reason == body["reason"] and log[(suppressed, "suprimir")].role == "admin"
                assert log[(expired, "vencer")].actor == "sistema · conservación"
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.email.like(f"test-ret-%-{scratch_unit}@example.com")))
            await session.commit()
