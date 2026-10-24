"""The unit's home figures (VRT-74) against the real API and Postgres: each
number with its previous period, the reasons grouped without quoting
anyone's data, and what needs a person, failures first."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, CaseRun, Document, ReviewItem, User
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]
_PASSWORD = "test-password-inicio"
DNI = "42285866"


def _reason(kind: str, decision: str, message: str, **ref) -> dict:
    return {"kind": kind, "decision": decision, "message": message, "ref": ref}


@pytest.mark.asyncio
async def test_the_home_figures_compare_and_never_quote_a_person(live_settings, scratch_unit):
    factory = get_session_factory(live_settings)
    now = datetime.now(UTC)
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            def case(verdict, created, reasons=(), ref=None):
                c = Case(status="completed", verdict=verdict, verdict_reasons=list(reasons), verdict_at=created + timedelta(minutes=5),
                         created_at=created, external_ref=ref)
                c.runs.append(CaseRun(run_number=1, trigger="submit", status="completed", finished_at=created + timedelta(minutes=4)))
                session.add(c)
                return c

            clean = case("continue", now - timedelta(hours=2))
            reviewed = case("continue", now - timedelta(hours=3))
            review = case("human_review", now - timedelta(days=1), [
                _reason("rule", "human_review", f"DNI del titular: los documentos no coinciden — {DNI} (Carta) frente a 42785091 (Seguro)",
                        rule_id="semantic.attribute_consistency"),
                _reason("pending_review", "human_review", "Hay campos pendientes de revisión humana."),
            ], ref="EXP-REV")
            client = case("return_to_client", now - timedelta(days=2), [
                _reason("missing_document", "return_to_client", "Falta: Boleta de pago", condition_key="boleta")], ref="EXP-CLI")
            case("continue", now - timedelta(days=9))  # the previous period
            await session.flush()
            docs = [Document(case_id=c.id, status=s, storage_key="k", original_filename="f.pdf")
                    for c, s in ((reviewed, "completed"), (review, "needs_review"), (client, "failed"))]
            session.add_all(docs)
            await session.flush()
            session.add_all([ReviewItem(document_id=docs[0].id, field_path="net_pay", current_value={"value": 1}, confidence=0.4, reason="low_confidence", status="resolved"),
                             ReviewItem(document_id=docs[1].id, field_path="dni", current_value={"value": DNI}, confidence=0.4, reason="low_confidence")])
            await UserRepository(session).create(name="Inicio", email=f"test-inicio-{scratch_unit}@example.com", password_hash=hash_password(_PASSWORD), role="visor")
            await session.commit()
            clean_id = clean.id
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client_http:
            token = (await client_http.post("/auth/login", json={"email": f"test-inicio-{scratch_unit}@example.com", "password": _PASSWORD})).json()["access_token"]
            response = await client_http.get("/v1/overview", params={"days": 7}, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        data = response.json()
        assert DNI not in response.text, "a reason names what failed, never the values"
        assert data["received"] == {"value": 4, "previous": 1}
        assert data["decided"] == 4 and data["straight_through"]["value"] == 0.25, "one of four, the one nobody had to look at"
        assert data["time_to_verdict_seconds"]["value"] == 240
        assert data["pending_review"] == 1 and data["in_review"] == 1 and data["waiting_client"] == 1 and data["failed_documents"] == 1
        assert sum(d["continued"] + d["human_review"] + d["return_to_client"] + d["in_progress"] for d in data["daily"]) == 4 and len(data["daily"]) == 7
        assert {(r["label"], r["decision"]) for r in data["reasons"]} == {
            ("DNI del titular: los documentos no coinciden", "human_review"), ("Falta: Boleta de pago", "return_to_client")}
        assert [(a["kind"], a["case_ref"]) for a in data["attention"]] == [("failed", "EXP-CLI"), ("review", "EXP-REV"), ("client", "EXP-CLI")]
        assert str(clean_id) not in {a["case_id"] for a in data["attention"]}
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.email == f"test-inicio-{scratch_unit}@example.com"))
            await session.commit()
