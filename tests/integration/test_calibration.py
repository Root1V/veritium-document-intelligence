"""Calibration against the real API and Postgres (VRT-43): observations come
from the latest completed run of each evaluation suite and from the human
reviews no evaluation already covers; computing makes a draft version and
only an admin activates it."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence.db import get_session_factory
from idp.persistence.models import AuditLogEntry, CalibrationVersion, Case, EvalCase, EvalResult, EvalRun, EvalSuite, ReviewItem
from idp.persistence.repositories import CalibrationRepository, CaseRepository, DocumentRepository, UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"
# A document type of its own, so other data in the database does not mix in.
_TYPE = f"t{uuid.uuid4().hex[:8]}"


def _result(run: EvalRun, case: EvalCase, match: bool) -> EvalResult:
    return EvalResult(run_id=run.id, case_id=case.id, status="done", predicted_document_type=_TYPE,
                      field_results=[{"field": "code", "expected": "1", "actual": "1" if match else "2", "confidence": 1.0, "match": match}])


@pytest.mark.asyncio
async def test_observations_compute_and_activation(live_settings):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
        case = await CaseRepository(session).create(external_ref=f"test-{uuid.uuid4()}")
        covered = await DocumentRepository(session).create(case_id=case.id, storage_key="stub", original_filename="a.png")
        reviewed = await DocumentRepository(session).create(case_id=case.id, storage_key="stub", original_filename="b.png")
        covered.document_type = reviewed.document_type = _TYPE

        suite = EvalSuite(name="calib", source="corrections", created_by="t")
        cases = [EvalCase(position=0, filename="a.png", storage_key="stub", expected_document_type=_TYPE, expected_fields={"code": "1"}, source_document_id=covered.id),
                 EvalCase(position=1, filename="c.png", storage_key="stub", expected_document_type=_TYPE, expected_fields={"code": "1"})]
        suite.cases = cases
        session.add(suite)
        await session.flush()
        old, latest = EvalRun(suite_id=suite.id, created_by="t", status="completed"), EvalRun(suite_id=suite.id, created_by="t", status="completed")
        session.add(old)
        await session.flush()
        session.add(latest)
        await session.flush()
        # the old run was all right; only the latest run counts: 1 right, 1 wrong
        session.add_all([_result(old, cases[0], True), _result(old, cases[1], True), _result(latest, cases[0], True), _result(latest, cases[1], False)])
        await session.execute(update(EvalRun).where(EvalRun.id == latest.id).values(created_at=EvalRun.created_at + timedelta(seconds=1)))

        for document in (covered, reviewed):  # the first is covered by the evaluation: not counted twice
            item = ReviewItem(document_id=document.id, field_path="code", current_value={"value": "9"}, confidence=0.99, reason="low_confidence", status="resolved")
            session.add(item)
            await session.flush()
            session.add(AuditLogEntry(review_item_id=item.id, original_value={"value": "9"}, original_confidence=0.99, reviewer_identity="t",
                                      corrected_value={"value": "1"}, reason_code="ocr_misread"))
        await session.commit()
        case_id, suite_id = case.id, suite.id

        observations, _ = await CalibrationRepository(session).observations()
        mine = [o for o in observations if o.key == f"{_TYPE}.code"]
        assert sorted((o.confidence, o.correct) for o in mine) == [(0.99, False), (1.0, False), (1.0, True)]

    version = None
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}
            created = await client.post("/v1/calibration", headers=h)
            assert created.status_code == 201, created.text
            body = created.json()
            version = body["version"]
            field = next(f for f in body["fields"] if f["key"] == f"{_TYPE}.code")
            assert field["count"] == 3 and field["accuracy"] == 0.3333 and field["preliminary"]
            assert [s["target_error"] for s in body["report"]["suggestions"]] == [0.01, 0.02, 0.05]

            activated = await client.post(f"/v1/calibration/{version}/activate", headers=h)
            assert activated.json()["status"] == "active"
            listed = (await client.get("/v1/calibration", headers=h)).json()
            assert listed[0]["version"] == version and listed[0]["status"] == "active"
            assert all(v["status"] != "active" for v in (await client.post("/v1/calibration/deactivate", headers=h)).json())
    finally:
        async with factory() as session:
            if version is not None:
                await session.execute(delete(CalibrationVersion).where(CalibrationVersion.version == version))
            await session.execute(delete(EvalSuite).where(EvalSuite.id == suite_id))
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.commit()
