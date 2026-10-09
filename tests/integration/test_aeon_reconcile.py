"""The worker's reconciler against real Postgres (VRT-26): aeon does not
call back, so a run whose aeon run failed before evaluation must be marked
failed by polling, and one that is still running must be left alone."""

from __future__ import annotations

import uuid

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete

from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, OutboxEvent
from idp.persistence.repositories import CaseRepository, CaseRunRepository
from idp.worker.__main__ import reconcile

pytestmark = [pytest.mark.usefixtures("require_postgres")]


@pytest.mark.asyncio
async def test_failed_aeon_runs_fail_the_case_run_and_running_ones_are_left(live_settings):
    settings = live_settings.model_copy(update={"aeon_api_token": SecretStr("test-token")})
    factory = get_session_factory(settings)
    async with factory() as session:
        case = await CaseRepository(session).create(external_ref=f"test-{uuid.uuid4()}")
        runs = CaseRunRepository(session)
        failed = await runs.create_next(case, trigger="submit")
        failed.status, failed.execution_ref = "running", f"test-failed-{uuid.uuid4()}"
        alive = await runs.create_next(case, trigger="documents_added")
        alive.status, alive.execution_ref = "running", f"test-alive-{uuid.uuid4()}"
        await session.commit()
        case_id, failed_id, alive_id = case.id, failed.id, alive.id
        statuses = {failed.execution_ref: "FAILED", alive.execution_ref: "RUNNING"}

    def aeon(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        ref = request.url.path.rsplit("/", 1)[-1]
        # Any other unfinished run in the dev database is reported RUNNING,
        # so this test never fails a real run.
        status = statuses.get(ref, "RUNNING")
        body = {"status": status}
        if status == "FAILED":  # aeon >= OBS-011 says why
            body["failure"] = {"kind": "failed", "type": "PolicyDenied", "message": "denied by policy", "activity": "check_activity_policy_activity", "retryable": False}
        return httpx.Response(200, json=body)

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(aeon)) as client:
            await reconcile(settings, client)
        async with factory() as session:
            runs = CaseRunRepository(session)
            failed_run, alive_run = await runs.get(failed_id), await runs.get(alive_id)
            assert failed_run.status == "failed" and "FAILED" in failed_run.error
            assert "PolicyDenied: denied by policy" in failed_run.error and "check_activity_policy_activity" in failed_run.error
            assert alive_run.status == "running"
    finally:
        async with factory() as session:
            await session.execute(delete(OutboxEvent).where(OutboxEvent.subject == str(case_id)))
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.commit()
