"""Business units (VRT-57) against the real API and Postgres. A unit's data
is planted directly in the database, never through the API (whose own
setup could be the hole). Then someone of another unit:

- reads nothing of it, by id or in lists, on every table: indistinguishable
  from a row that does not exist (404, never 403);
- cannot change it;
and the unit's own people can (the negative control: without it, the 404s
would pass with everything broken). People work in several units, one
token per unit; no route answers without one."""

from __future__ import annotations

import importlib
import pkgutil
import uuid

import pytest
from fastapi import APIRouter
from fastapi.dependencies.models import Dependant
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

import idp.api.routes as routes
from idp.api.app import create_app
from idp.api.deps import get_principal
from idp.auth.security import hash_password
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import (
    Base,
    Case,
    CaseCondition,
    CaseRun,
    Document,
    Extraction,
    Membership,
    OutboxEvent,
    ReviewItem,
    User,
    ValidationIssue,
    WebhookEndpoint,
)
from idp.persistence.repositories import ProcessProfileRepository, UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio")]
_PASSWORD = "test-password-unidades"


async def _plant(factory, unit: str) -> dict[str, uuid.UUID]:
    """A case with everything hanging from it, in ``unit``, straight into the database."""
    with tenancy.acting_for(unit):
        async with factory() as session:
            await ProcessProfileRepository(session).ensure_seed()
            profile = await ProcessProfileRepository(session).get_by_key("convenios")
            version = ProcessProfileRepository.latest_published(profile)
            case = Case(status="completed", profile_version_id=version.id, external_ref=f"UNIDAD-{unit}", verdict="human_review")
            session.add(case)
            await session.flush()
            run = CaseRun(case_id=case.id, run_number=1, trigger="submit", status="completed")
            document = Document(case_id=case.id, status="needs_review", document_type="payslip", storage_key=f"{unit}/x.pdf", original_filename="boleta.pdf")
            session.add_all([run, document])
            await session.flush()
            review = ReviewItem(document_id=document.id, field_path="net_pay", current_value={"value": 1}, confidence=0.4, reason="low_confidence")
            session.add_all([
                Extraction(document_id=document.id, schema_version="1", payload={"net_pay": {"value": 1}}, parser_backend="rapidocr", extraction_method="agentic"),
                ValidationIssue(case_id=case.id, document_id=document.id, rule_id="r", category="self", severity="warning", message="m", confidence=1, confidence_method="rule", explanation="e"),
                review,
                CaseCondition(case_id=case.id, key="solicitud", label="Solicitud", kind="missing_document"),
                OutboxEvent(type="pe.veritium.case.run.completed", subject=str(case.id), data={"case_id": str(case.id)}),
            ])
            endpoint = WebhookEndpoint(url="https://example.com/hook", event_types=[], secret_ciphertext="x")
            session.add(endpoint)
            await session.commit()
            return {"case": case.id, "document": document.id, "review": review.id, "endpoint": endpoint.id, "profile": profile.id}


async def _person(factory, email: str, roles: dict[str, str]) -> None:
    async with factory() as session:
        users = UserRepository(session)
        user = await users.create(name=email.split("@")[0], email=email, password_hash=hash_password(_PASSWORD))
        for unit, role in roles.items():
            await users.set_membership(user.id, unit, role)
        await session.commit()


@pytest.mark.asyncio
async def test_a_unit_sees_nothing_of_another(live_settings, scratch_unit, other_unit):
    factory = get_session_factory(live_settings)
    planted = await _plant(factory, scratch_unit)
    own, outsider = f"test-own-{scratch_unit}@example.com", f"test-out-{other_unit}@example.com"
    await _person(factory, own, {scratch_unit: "admin"})
    await _person(factory, outsider, {other_unit: "admin"})
    try:
        # Every table of a unit, straight through the ORM: another unit gets nothing back, nor changes anything.
        with tenancy.system():
            async with factory() as session:
                rows = {
                    m.class_: (await session.scalars(select(m.class_).where(m.class_.tenant == scratch_unit))).all()
                    for m in Base.registry.mappers if issubclass(m.class_, tenancy.TenantScoped)
                }
        covered = {cls.__tablename__ for cls, found in rows.items() if found}
        assert {"cases", "case_runs", "documents", "extractions", "validation_issues", "review_items", "case_conditions",
                "outbox_events", "webhook_endpoints", "process_profiles", "process_profile_versions"} <= covered
        for cls, found in rows.items():
            for row in found:
                pk = cls.__mapper__.primary_key[0]
                with tenancy.acting_for(other_unit):
                    async with factory() as session:
                        assert await session.get(cls, getattr(row, pk.key)) is None, cls.__name__
                        assert (await session.execute(update(cls).where(pk == getattr(row, pk.key)).values(tenant=other_unit))).rowcount == 0, cls.__name__
                        assert (await session.execute(delete(cls).where(pk == getattr(row, pk.key)))).rowcount == 0, cls.__name__
                        await session.commit()
                with tenancy.acting_for(scratch_unit):  # negative control: its own unit still has it
                    async with factory() as session:
                        assert await session.get(cls, getattr(row, pk.key)) is not None, cls.__name__

        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            async def token(email: str) -> dict[str, str]:
                return {"Authorization": f"Bearer {(await client.post('/auth/login', json={'email': email, 'password': _PASSWORD})).json()['access_token']}"}

            mine, theirs = await token(own), await token(outsider)
            by_id = [
                f"/v1/cases/{planted['case']}", f"/v1/cases/{planted['case']}/result", f"/batches/{planted['case']}",
                f"/documents/{planted['document']}", f"/v1/webhook-endpoints/{planted['endpoint']}/deliveries",
            ]
            for path in by_id:
                assert (await client.get(path, headers=mine)).status_code == 200, path
                assert (await client.get(path, headers=theirs)).status_code == 404, path  # as if it did not exist
            correction = {"corrected_value": 2, "reason_code": "ocr_misread"}
            assert (await client.post(f"/review/{planted['review']}", headers=theirs, json=correction)).status_code == 404
            assert (await client.delete(f"/v1/webhook-endpoints/{planted['endpoint']}", headers=theirs)).status_code == 404

            assert str(planted["case"]) in {c["id"] for c in (await client.get("/v1/cases", headers=mine)).json()}
            assert (await client.get("/v1/cases", headers=theirs)).json() == []
            assert (await client.get("/review", headers=theirs)).json() == []
            assert (await client.get("/v1/webhook-endpoints", headers=theirs)).json() == []
            assert "convenios" not in {p["key"] for p in (await client.get("/v1/profiles", headers=theirs)).json()}
            assert {u["email"] for u in (await client.get("/users", headers=theirs)).json()} == {outsider}
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.email.in_([own, outsider])))
            await session.commit()


@pytest.mark.asyncio
async def test_a_person_works_in_several_units_one_token_each(live_settings, scratch_unit, other_unit):
    factory = get_session_factory(live_settings)
    email = f"test-both-{scratch_unit}@example.com"
    await _person(factory, email, {scratch_unit: "admin", other_unit: "visor"})
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            first = (await client.post("/auth/login", json={"email": email, "password": _PASSWORD, "tenant": other_unit})).json()
            assert first["tenant"] == other_unit and first["role"] == "visor"
            assert {u["key"]: u["role"] for u in first["tenants"]} == {scratch_unit: "admin", other_unit: "visor"}
            in_other = {"Authorization": f"Bearer {first['access_token']}"}
            assert (await client.get("/users", headers=in_other)).status_code == 403, "visor there"

            switched = await client.post("/auth/switch", headers=in_other, json={"tenant": scratch_unit})
            in_scratch = {"Authorization": f"Bearer {switched.json()['access_token']}"}
            assert (await client.get("/users", headers=in_scratch)).status_code == 200, "admin here"
            assert (await client.get("/auth/me", headers=in_scratch)).json()["tenant"] == scratch_unit
            assert (await client.post("/auth/switch", headers=in_scratch, json={"tenant": "default"})).status_code == 403

            # Out of a unit: its token stops at once, the other one still works.
            async with factory() as session:
                user = await UserRepository(session).get_by_email(email)
                await session.execute(delete(Membership).where(Membership.user_id == user.id, Membership.tenant == scratch_unit))
                await session.commit()
            assert (await client.get("/v1/cases", headers=in_scratch)).status_code == 401
            assert (await client.get("/v1/cases", headers=in_other)).status_code == 200
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.email == email))
            await session.commit()


def _depends_on(dependant: Dependant, call) -> bool:
    return dependant.call is call or any(_depends_on(d, call) for d in dependant.dependencies)


def test_no_route_answers_without_knowing_the_unit():
    """Every route needs a credential, which names the unit — except the few
    that are the way in, and the upload link, which is its own credential."""
    public = {
        "POST /auth/login", "POST /auth/token", "GET /auth/providers", "GET /auth/oidc/login", "GET /auth/oidc/callback", "GET /auth/oidc/logout",
        "GET /.well-known/oauth-authorization-server",
    }
    by_link = "/v1/upload-sessions/{session_id}"
    unguarded = []
    for module in pkgutil.iter_modules(routes.__path__):
        for router in vars(importlib.import_module(f"{routes.__name__}.{module.name}")).values():
            if not isinstance(router, APIRouter):
                continue
            for route in router.routes:
                names = {f"{m} {route.path}" for m in route.methods}
                if names & public or route.path.startswith(by_link):
                    continue
                if not _depends_on(route.dependant, get_principal):
                    unguarded.append(sorted(names)[0])
    assert not unguarded, f"rutas que no conocen la unidad de quien llama: {unguarded}"
