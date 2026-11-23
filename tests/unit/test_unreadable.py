"""VRT-112: a field the document carries but that cannot be read is not a
missing one — the client sends a clearer copy of that page, not the
document — and a person reviews it with that reason. No DB, no LLM."""

from __future__ import annotations

import uuid

from idp.domain.completeness import evaluate_checklist
from idp.domain.document_type_catalog import compile_schema
from idp.domain.document_type_seed import seed_definitions
from idp.domain.process_profile_seed import convenios_definition
from idp.domain.semantic_resolution import DocumentExtraction, resolve_case
from idp.domain.semantic_seed import seed_catalog
from idp.domain.verdict import OpenCondition, VerdictInputs, decide
from idp.extraction.grounding import attach_grounding
from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.pipeline.case_evaluation import _unreadable_note
from idp.review.corrections import apply_correction
from idp.review.routing import find_review_candidates

PAYSLIP = compile_schema(next(d for d in seed_definitions() if d.key == "payslip"))


def _env(value, confidence: float = 0.95) -> dict:
    return {"value": value, "confidence": confidence, "source_text": str(value), "page": 0}


def _payslip(**extra) -> dict:
    """A payslip whose net pay is there but blurred: the agent wrote its best reading and said so."""
    return {
        "employee_name": _env("SALAS SIGUAS, KATERIN KAROLA"),
        "period": _env("ENERO - 2026"),
        "gross_pay": _env(6618.0),
        "total_deductions": _env(2313.86),
        "net_pay": _env(4304.0, confidence=0.2),
        "unreadable_fields": [{"field": "net_pay", "why": "blurry", "region_id": 7, "page": 1}],
        **extra,
    }


def _income(*extractions):
    view = resolve_case(seed_catalog(), list(extractions))
    return view, next(o for o in evaluate_checklist(convenios_definition(), [], view, {}) if o.item.key == "evidencia_ingreso")


def test_an_unreadable_value_is_not_evidence_and_says_where_it_is():
    payslip = uuid.uuid4()
    view, income = _income(DocumentExtraction(document_id=payslip, document_type="payslip", payload=_payslip()))
    assert view.get("titular", "ingreso.neto_mensual") is None  # its best reading does not count
    assert not income.satisfied
    assert income.condition_kind == "unreadable_evidence"
    assert [(u.document_id, u.page, u.why) for u in income.unreadable] == [(payslip, 1, "blurry")]
    assert _unreadable_note(income) == "pág. 2, borroso"


def test_another_document_that_can_be_read_satisfies_it():
    _, income = _income(
        DocumentExtraction(document_id=uuid.uuid4(), document_type="payslip", payload=_payslip()),
        DocumentExtraction(document_id=uuid.uuid4(), document_type="debt_capacity_calculation", payload={"net_income": _env(4300.0)}),
    )
    assert income.satisfied and not income.unreadable


def test_a_value_the_document_does_not_carry_is_still_missing():
    payload = _payslip(unreadable_fields=[])
    del payload["net_pay"]
    _, income = _income(DocumentExtraction(document_id=uuid.uuid4(), document_type="payslip", payload=payload))
    assert income.condition_kind == "missing_evidence"


def test_the_verdict_asks_the_client_for_a_clear_copy():
    verdict = decide(VerdictInputs(open_conditions=[OpenCondition(key="i", label="Evidencia de ingreso", kind="unreadable_evidence")]), None)
    assert verdict.decision == "return_to_client"
    assert [(r.kind, r.message) for r in verdict.reasons] == [("unreadable_evidence", "No se lee: Evidencia de ingreso")]


def test_a_person_reviews_it_with_that_reason():
    candidates = find_review_candidates(PAYSLIP.model_validate(_payslip()), [], confidence_threshold=0.75)
    assert [(c.field_path, c.reason) for c in candidates] == [("net_pay", "unreadable")]


def test_once_a_person_reads_it_it_is_evidence():
    corrected = apply_correction(_payslip(), "net_pay", 4304.14, PAYSLIP)
    assert corrected["unreadable_fields"] == []
    _, income = _income(DocumentExtraction(document_id=uuid.uuid4(), document_type="payslip", payload=corrected))
    assert income.satisfied


def test_the_page_to_ask_for_comes_from_the_region():
    parsed = ParsedDocument(backend="test", page_count=2, blocks=[ParsedBlock(region_id=7, text="NETO A PAGAR", page=1, bbox=[0, 0, 1, 1], confidence=0.9)])
    instance = PAYSLIP.model_validate(_payslip(unreadable_fields=[{"field": "net_pay", "why": "blurry", "region_id": 7}]))
    attach_grounding(instance, parsed)
    assert instance.model_dump()["unreadable_fields"][0]["page"] == 1
