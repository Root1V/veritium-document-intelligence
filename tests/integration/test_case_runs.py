"""Case runs against real Postgres (VRT-25), without an LLM: extraction is
replaced by a stub that saves a fixed payload, so what is under test is the
run lifecycle itself.

Covers the regression found while building VRT-25: documents extracted
inside a run must reach validation. The case is loaded before extraction,
so its Document objects sit in the session's identity map with
extraction=None; ``DocumentRepository.list_for_case`` must refresh them
(populate_existing) or validation silently skips every document."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, func, select

from idp.domain.envelope import Extracted
from idp.domain.schemas.insurance_disclosure import InsuranceDisclosureSchema
from idp.domain.schemas.loan_application import LoanApplicationSchema
from idp.domain.schemas.payslip import PayslipSchema
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, CaseCondition, OutboxEvent, ReviewItem, ValidationIssue
from idp.persistence.repositories import (
    CaseConditionRepository,
    CaseRepository,
    CaseRunRepository,
    DocumentRepository,
    ProcessProfileRepository,
    ReferenceDataRepository,
)
from idp.pipeline import orchestrator
from idp.pipeline.case_evaluation import refresh_verdict
from idp.validation.ports import StubExternalSystemPort

pytestmark = [pytest.mark.usefixtures("require_postgres")]


def _payload(dni: str) -> dict:
    return InsuranceDisclosureSchema(
        insured_first_name=Extracted[str](value="ANA", page=1, confidence=0.99),
        insured_dni=Extracted[str](value=dni, page=1, confidence=0.3),  # low confidence → review candidate
    ).model_dump(mode="json")


@pytest.fixture
def stub_extraction(monkeypatch):
    """Replaces parse/classify/extract with: mark the document as an
    insurance disclosure and save a fixed extraction."""

    async def fake_process(*, session, document_id, extraction_repo, document_repo, **_):
        doc = await document_repo.get(document_id)
        doc.document_type = "insurance_disclosure"
        await extraction_repo.save(
            document_id=document_id, schema_version="1.0", payload=_payload("1234567X"), parser_backend="stub", extraction_method="fixed"
        )
        await document_repo.set_status(document_id, "extracted")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", fake_process)


async def _run(settings, session, case: Case) -> uuid.UUID:
    run = await CaseRunRepository(session).create_next(case, trigger="submit")
    await session.commit()
    await orchestrator.process_case_run(
        settings=settings,
        session=session,
        case_id=case.id,
        run_id=run.id,
        object_store=None,  # type: ignore[arg-type]  # unused: extraction is stubbed
        reference_data=ReferenceDataRepository(session),
        external_system=StubExternalSystemPort(),
    )
    return run.id


@pytest.mark.asyncio
async def test_documents_extracted_in_a_run_are_validated_and_rerun_supersedes(live_settings, stub_extraction):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        case = await CaseRepository(session).create(external_ref=f"test-{uuid.uuid4()}")
        doc = await DocumentRepository(session).create(case_id=case.id, storage_key="stub", original_filename="seguro.png")
        await session.commit()
        case_id, doc_id = case.id, doc.id
        try:
            run1 = await _run(live_settings, session, case)

            document = await DocumentRepository(session).get(doc_id)
            assert document is not None
            assert document.status in ("completed", "needs_review"), "the document never reached validation"
            issues_run1 = (await session.scalars(select(ValidationIssue).where(ValidationIssue.case_id == case_id))).all()
            assert issues_run1, "the malformed DNI should produce at least one issue"
            assert all(i.case_run_id == run1 for i in issues_run1)
            reviews_run1 = await session.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.document_id == doc_id))

            # Second run: nothing new to extract; the case is re-evaluated.
            run2 = await _run(live_settings, session, await CaseRepository(session).get(case_id))  # type: ignore[arg-type]
            active = (await session.scalars(select(ValidationIssue).where(ValidationIssue.case_id == case_id, ValidationIssue.superseded_at.is_(None)))).all()
            superseded = (await session.scalars(select(ValidationIssue).where(ValidationIssue.case_id == case_id, ValidationIssue.superseded_at.is_not(None)))).all()
            assert {i.case_run_id for i in active} == {run2}
            assert len(superseded) == len(issues_run1)
            reviews_run2 = await session.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.document_id == doc_id))
            assert reviews_run2 == reviews_run1, "a re-evaluation must not ask a human twice about the same field"
        finally:
            await session.execute(delete(OutboxEvent).where(OutboxEvent.subject == str(case_id)))
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.commit()


# --- VRT-27: checklist conditions and verdict over a convenios case --------



def _e(value):
    return Extracted(value=value, page=1, confidence=0.99)


_PAYLOADS = {
    "seguro.png": ("insurance_disclosure", InsuranceDisclosureSchema(
        insured_first_name=_e("ANA"), insured_paternal_surname=_e("PEREZ"), insured_maternal_surname=_e("ROJAS"), insured_dni=_e("12345678"))),
    "boleta.png": ("payslip", PayslipSchema(
        employee_name=_e("PEREZ ROJAS, ANA"), period=_e("09/2026"), gross_pay=_e(1000.0), total_deductions=_e(200.0), net_pay=_e(800.0))),
    "solicitud.pdf": ("loan_application", LoanApplicationSchema(
        applicant_first_name=_e("ANA"), applicant_paternal_surname=_e("PEREZ"), applicant_maternal_surname=_e("ROJAS"), applicant_dni=_e("12345678"))),
}


@pytest.fixture
def stub_extraction_by_filename(monkeypatch):
    async def fake_process(*, session, document_id, extraction_repo, document_repo, **_):
        doc = await document_repo.get(document_id)
        doc_type, instance = _PAYLOADS[doc.original_filename]
        doc.document_type = doc_type
        await extraction_repo.save(
            document_id=document_id, schema_version="1.0", payload=instance.model_dump(mode="json"), parser_backend="stub", extraction_method="fixed"
        )
        await document_repo.set_status(document_id, "extracted")
        await session.commit()
        return []

    monkeypatch.setattr(orchestrator, "_process_uploaded_file", fake_process)


@pytest.mark.asyncio
async def test_convenios_case_conditions_and_verdict_across_runs(live_settings, stub_extraction_by_filename):
    factory = get_session_factory(live_settings)
    async with factory() as session:
        profile = await ProcessProfileRepository(session).get_by_key("convenios")
        assert profile is not None
        version = ProcessProfileRepository.latest_published(profile)
        case = await CaseRepository(session).create(
            external_ref=f"test-{uuid.uuid4()}", profile_version_id=version.id, request_input_payload={"nacionalidad": "PE"}
        )
        for name in ("seguro.png", "boleta.png"):
            await DocumentRepository(session).create(case_id=case.id, storage_key="stub", original_filename=name)
        await session.commit()
        case_id = case.id
        try:
            # Run 1: loan application and authorization letter are missing.
            await _run(live_settings, session, await CaseRepository(session).get(case_id))  # type: ignore[arg-type]
            case = await CaseRepository(session).get(case_id)
            conditions = {c.key: c for c in await CaseConditionRepository(session).list_for_case(case_id)}
            assert {k for k, c in conditions.items() if c.status == "open"} == {"solicitud", "autorizacion_descuento"}
            assert "evidencia_ingreso" not in conditions  # satisfied by the payslip
            assert "carne_extranjeria" not in conditions  # nacionalidad PE → not applicable
            assert case.verdict == "return_to_client"

            # Waiving one requirement recomputes the verdict without a run.
            await CaseConditionRepository(session).waive(conditions["autorizacion_descuento"], by="test", reason="presentada en físico")
            verdict = await refresh_verdict(session, case_id)
            await session.commit()
            assert verdict.decision == "return_to_client"  # the application is still missing

            # Run 2: the loan application arrives.
            loan = await DocumentRepository(session).create(case_id=case_id, storage_key="stub", original_filename="solicitud.pdf")
            await session.commit()
            await _run(live_settings, session, await CaseRepository(session).get(case_id))  # type: ignore[arg-type]
            case = await CaseRepository(session).get(case_id)
            conditions = {c.key: c for c in await CaseConditionRepository(session).list_for_case(case_id)}
            assert conditions["solicitud"].status == "resolved" and conditions["solicitud"].resolved_by_document_id == loan.id
            assert conditions["autorizacion_descuento"].status == "waived"
            assert case.verdict == "continue", case.verdict_reasons
            assert [r.verdict for r in sorted(case.runs, key=lambda r: r.run_number)] == ["return_to_client", "continue"]
        finally:
            await session.execute(delete(CaseCondition).where(CaseCondition.case_id == case_id))
            await session.execute(delete(OutboxEvent).where(OutboxEvent.subject == str(case_id)))
            await session.execute(delete(Case).where(Case.id == case_id))
            await session.commit()
