"""What-if and shadow simulations against the real API and Postgres (VRT-44),
without an LLM: extraction is a stub. A candidate version of `convenios`
that no longer requires the loan application or the authorization letter
would let a case that today is returned to the client continue — and the
case itself must stay exactly as it was."""

from __future__ import annotations

import random
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.config import get_settings
from idp.domain.envelope import Extracted
from idp.domain.process_profile import ProcessProfileDefinition
from idp.domain.schemas.insurance_disclosure import InsuranceDisclosureSchema
from idp.domain.schemas.payslip import PayslipSchema
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, CaseCondition, OutboxEvent, ProcessProfileVersion, Simulation, SimulationResult
from idp.persistence.repositories import CaseRepository, CaseRunRepository, DocumentRepository, ProcessProfileRepository, UserRepository
from idp.pipeline import orchestrator

pytestmark = [pytest.mark.usefixtures("require_postgres")]

_ADMIN, _PASSWORD = "test-admin@example.com", "test-admin-password"


def _e(value: object) -> Any:
    return Extracted(value=value, page=1, confidence=0.99)


_PAYLOADS = {
    "seguro.png": ("insurance_disclosure", InsuranceDisclosureSchema(
        insured_first_name=_e("ANA"), insured_paternal_surname=_e("PEREZ"), insured_maternal_surname=_e("ROJAS"), insured_dni=_e("12345678"))),
    "boleta.png": ("payslip", PayslipSchema(
        employee_name=_e("PEREZ ROJAS, ANA"), period=_e("09/2026"), gross_pay=_e(1000.0), total_deductions=_e(200.0), net_pay=_e(800.0))),
}


@pytest.fixture
def stub_extraction(monkeypatch):
    async def fake_process(*, session, document_id, extraction_repo, document_repo, **_):
        doc = await document_repo.get(document_id)
        doc_type, instance = _PAYLOADS[doc.original_filename]
        doc.document_type = doc_type
        await extraction_repo.save(document_id=document_id, schema_version="1.0", payload=instance.model_dump(mode="json"), parser_backend="stub", extraction_method="fixed")
        await document_repo.set_status(document_id, "extracted")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", fake_process)
    monkeypatch.setenv("CASE_EXECUTOR", "in_process")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _run(settings, session, case_id) -> uuid.UUID:
    run = await CaseRunRepository(session).create_next(await CaseRepository(session).get(case_id), trigger="submit")  # type: ignore[arg-type]
    await session.commit()
    run_id = run.id
    await orchestrator.process_case_run(settings=settings, case_id=case_id, run_id=run_id)
    session.expire_all()
    return run_id


@pytest.mark.asyncio
async def test_what_if_and_shadow_decide_with_the_candidate_without_touching_the_case(live_settings, stub_extraction):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        users = UserRepository(session)
        if await users.get_by_email(_ADMIN) is None:
            await users.create(name="Test Admin", email=_ADMIN, password_hash=hash_password(_PASSWORD), role="admin")
        profile = await ProcessProfileRepository(session).get_by_key("convenios")
        assert profile is not None
        published = ProcessProfileRepository.latest_published(profile)
        assert published is not None
        definition = ProcessProfileDefinition.model_validate(published.definition)
        relaxed = definition.model_copy(update={"checklist": [i for i in definition.checklist if i.key not in ("solicitud", "autorizacion_descuento")]})
        # Retired, not draft: a test must not take the profile's one draft slot.
        candidate = ProcessProfileVersion(
            profile_id=profile.id, version=random.randint(9000, 99999), status="retired", definition=relaxed.model_dump(mode="json"),
            content_hash="test", semantic_catalog_version=published.semantic_catalog_version, created_by="test",
        )
        session.add(candidate)
        case = await CaseRepository(session).create(external_ref=f"test-{uuid.uuid4()}", profile_version_id=published.id, request_input_payload={"nacionalidad": "PE"})
        for name in _PAYLOADS:
            await DocumentRepository(session).create(case_id=case.id, storage_key="stub", original_filename=name)
        await session.commit()
        case_id, candidate_id, candidate_version = case.id, candidate.id, candidate.version

    simulation_ids: list[str] = []
    try:
        async with factory() as session:
            await _run(live_settings, session, case_id)
            before = await CaseRepository(session).get(case_id)
            assert before is not None and before.verdict == "return_to_client"
            real_reasons = before.verdict_reasons

        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            token = (await client.post("/auth/login", json={"email": _ADMIN, "password": _PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}

            # Our case is the newest convenios case: a limit of 1 takes only it.
            started = await client.post("/v1/simulations", headers=h, json={"profile_key": "convenios", "profile_version": candidate_version, "case_limit": 1})
            assert started.status_code == 202, started.text
            simulation_ids.append(started.json()["id"])
            detail = (await client.get(f"/v1/simulations/{started.json()['id']}", headers=h)).json()
            assert detail["status"] == "completed"
            change = detail["cases"][0]
            assert change["case_id"] == str(case_id)
            assert (change["actual_verdict"], change["simulated_verdict"]) == ("return_to_client", "continue")
            assert "Falta: Solicitud de préstamo por convenio" in change["removed_reasons"]
            assert detail["summary"]["changed"] == 1
            assert detail["summary"]["transitions"] == [{"before": "return_to_client", "after": "continue", "count": 1}]

            async with factory() as session:
                after = await CaseRepository(session).get(case_id)
                assert after is not None and (after.verdict, after.verdict_reasons) == ("return_to_client", real_reasons), "a simulation never touches the case"

            shadow = await client.post("/v1/simulations", headers=h, json={"profile_key": "convenios", "profile_version": candidate_version, "kind": "shadow"})
            assert shadow.status_code == 202 and shadow.json()["status"] == "running"
            simulation_ids.append(shadow.json()["id"])
            async with factory() as session:
                run_id = await _run(live_settings, session, case_id)  # a new real run: the shadow decides it too
                recorded = await session.scalar(select(SimulationResult).where(SimulationResult.simulation_id == uuid.UUID(shadow.json()["id"])))
                assert recorded is not None and recorded.case_run_id == run_id and recorded.simulated_verdict == "continue"
                assert (await CaseRepository(session).get(case_id)).verdict == "return_to_client"  # type: ignore[union-attr]
            stopped = await client.post(f"/v1/simulations/{shadow.json()['id']}/stop", headers=h)
            assert stopped.json()["status"] == "stopped" and stopped.json()["summary"]["agreement"] == 0.0
    finally:
        async with factory() as session:
            await session.execute(delete(Simulation).where(Simulation.id.in_([uuid.UUID(i) for i in simulation_ids])))
            await session.execute(delete(CaseCondition).where(CaseCondition.case_id == case_id))
            await session.execute(delete(OutboxEvent).where(OutboxEvent.subject == str(case_id)))
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.execute(delete(ProcessProfileVersion).where(ProcessProfileVersion.id == candidate_id))
            await session.commit()
