"""Unit tests for VRT-40: which rules a selective reprocess re-evaluates
(the field → rule graph), how a CEL rule's reads are derived, and how a
correction is written into an extraction. No DB, no LLM."""

from __future__ import annotations

import uuid

import pytest

from idp.domain.document_type_seed import seed_definitions
from idp.domain.document_type_catalog import compile_schema
from idp.domain.reprocess import ReprocessScope, changed_reads, rules_to_reevaluate
from idp.domain.semantic_seed import seed_catalog
from idp.pipeline.orchestrator import _hardcoded_rules
from idp.review.corrections import apply_correction
from idp.validation.rules.generic import cel_reads
from idp.validation.rules.semantic_rules import format_rules

PAYSLIP = compile_schema(next(d for d in seed_definitions() if d.key == "payslip"))


def _rules():
    from idp.config import Settings

    return _hardcoded_rules(Settings()) + format_rules(seed_catalog())


def _ids(rules) -> set[str]:
    return {r.rule_id for r in rules}


def test_a_corrected_field_reaches_only_the_rules_that_read_it() -> None:
    scope = ReprocessScope(kind="attribute", document_id=uuid.uuid4(), field_path="employee_code")
    selected = _ids(rules_to_reevaluate(_rules(), scope, changed_reads(scope, seed_catalog(), document_type="payslip")))
    assert selected == {
        "request_input.expected_employee_code_matches",
        "batch.duplicate_identifier",
        "reference_data.employee_code_exists",
        "reference_data.employee_name_matches_reference",
        # employee_code maps to persona.codigo_empleado: the cross-document check reads every attribute
        "semantic.attribute_consistency",
    }


def test_an_attribute_reaches_its_format_rule_and_the_fields_mapped_to_it() -> None:
    scope = ReprocessScope(kind="attribute", attribute="persona.dni")
    selected = _ids(rules_to_reevaluate(_rules(), scope, changed_reads(scope, seed_catalog(), document_type=None)))
    assert "semantic.format.persona.dni" in selected
    assert "semantic.attribute_consistency" in selected
    assert "self.payslip_arithmetic_consistency" not in selected


def test_an_unmapped_field_does_not_reach_the_attribute_rules() -> None:
    scope = ReprocessScope(kind="attribute", document_id=uuid.uuid4(), field_path="period")
    assert _ids(rules_to_reevaluate(_rules(), scope, changed_reads(scope, seed_catalog(), document_type="payslip"))) == set()


def test_a_rule_scope_brings_the_rules_it_depends_on() -> None:
    rules = _rules()
    rules[0].depends_on = ["reference_data.employee_code_exists"]
    try:
        selected = _ids(rules_to_reevaluate(rules, ReprocessScope(kind="rule", rule_id=rules[0].rule_id), set()))
    finally:
        rules[0].depends_on = []
    assert selected == {rules[0].rule_id, "reference_data.employee_code_exists"}


def test_a_scope_needs_its_target() -> None:
    with pytest.raises(ValueError):
        ReprocessScope(kind="document")
    with pytest.raises(ValueError):
        ReprocessScope(kind="attribute", field_path="employee_code")


def test_cel_reads_fields_and_case_attributes() -> None:
    reads = cel_reads(["has(doc.net_pay) && doc.net_pay > case.titular.ingreso.neto_mensual * 0.5"], attribute=None)
    assert reads == frozenset({"net_pay", "@ingreso.neto_mensual"})
    assert cel_reads(["value > 1025.0"], attribute="ingreso.neto_mensual") == frozenset({"@ingreso.neto_mensual"})


def test_cel_reads_is_unknown_when_doc_is_used_another_way() -> None:
    assert cel_reads(['doc["net_pay"] > 0.0'], attribute=None) is None


PAYLOAD = {
    "employee_name": {"value": "SALAS SIGUAS, KATERIN", "confidence": 0.9, "page": 0},
    "employee_code": {"value": "011858", "confidence": 0.5, "page": 0, "bbox": [0.1, 0.1, 0.2, 0.2]},
    "period": {"value": "2026-01", "confidence": 0.9},
    "gross_pay": {"value": 1200.0, "confidence": 0.9},
    "total_deductions": {"value": 200.0, "confidence": 0.9},
    "net_pay": {"value": 1000.0, "confidence": 0.9},
}


def test_a_correction_replaces_the_value_and_keeps_the_evidence() -> None:
    corrected = apply_correction(PAYLOAD, "employee_code", "011859", PAYSLIP)
    assert corrected["employee_code"]["value"] == "011859"
    assert corrected["employee_code"]["confidence"] == 1.0
    assert corrected["employee_code"]["bbox"] == [0.1, 0.1, 0.2, 0.2]
    assert PAYLOAD["employee_code"]["value"] == "011858"  # the input is not mutated


def test_a_correction_is_coerced_to_the_field_type() -> None:
    assert apply_correction(PAYLOAD, "net_pay", "1025.5", PAYSLIP)["net_pay"]["value"] == 1025.5


def test_a_correction_that_does_not_fit_is_rejected() -> None:
    with pytest.raises(ValueError, match="no es válido"):
        apply_correction(PAYLOAD, "net_pay", "mil", PAYSLIP)
    with pytest.raises(ValueError, match="no existe"):
        apply_correction(PAYLOAD, "concepts[3].amount", "1", PAYSLIP)
