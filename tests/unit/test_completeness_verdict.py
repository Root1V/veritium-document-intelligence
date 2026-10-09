"""Unit tests for VRT-27: checklist evaluation (by type, by attribute with
alternative documents, conditional, fail-closed), the verdict precedence,
and how a profile selects rules and overrides severities. No DB, no LLM."""

from __future__ import annotations

import uuid

from idp.domain.completeness import CaseDocument, evaluate_checklist
from idp.domain.process_profile import ChecklistItem, ProcessProfileDefinition, RuleBinding
from idp.domain.process_profile_seed import convenios_definition
from idp.domain.semantic_resolution import DocumentExtraction, resolve_case
from idp.domain.semantic_seed import seed_catalog
from idp.domain.verdict import FindingInput, OpenCondition, VerdictInputs, decide
from idp.pipeline.case_evaluation import apply_binding, rules_for_profile
from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult
from idp.validation.rules.semantic_rules import SemanticAttributeConsistency
from idp.validation.rules.self_rules import PayslipArithmeticConsistency


def _env(value) -> dict:
    return {"value": value, "page": 1, "confidence": 0.9}


def _outcomes(definition, documents, extractions=(), request=None):
    view = resolve_case(seed_catalog(), list(extractions)) if extractions else None
    return {o.item.key: o for o in evaluate_checklist(definition, documents, view, request or {})}


# --- checklist -------------------------------------------------------------


def test_requirement_by_type_counts_only_non_failed_documents_of_that_type():
    d = ProcessProfileDefinition(semantic_catalog_version=1, checklist=[ChecklistItem(key="sol", label="Solicitud", document_type="loan_application")])
    ok = _outcomes(d, [CaseDocument(uuid.uuid4(), "loan_application", "completed")])["sol"]
    failed = _outcomes(d, [CaseDocument(uuid.uuid4(), "loan_application", "failed")])["sol"]
    assert ok.applicable and ok.satisfied
    assert failed.applicable and not failed.satisfied


def test_income_evidence_is_satisfied_by_alternative_documents():
    """convenios' 'evidencia_ingreso' accepts a payslip OR a debt capacity
    calculation — whichever maps to titular.ingreso.neto_mensual."""
    d = convenios_definition()
    payslip_id, calc_id = uuid.uuid4(), uuid.uuid4()
    via_payslip = _outcomes(d, [], [DocumentExtraction(document_id=payslip_id, document_type="payslip", payload={"net_pay": _env(4304.14)})])
    via_calc = _outcomes(d, [], [DocumentExtraction(document_id=calc_id, document_type="debt_capacity_calculation", payload={"net_income": _env(4300.0)})])
    neither = _outcomes(d, [], [DocumentExtraction(document_id=uuid.uuid4(), document_type="insurance_disclosure", payload={"insured_dni": _env("12345678")})])
    assert via_payslip["evidencia_ingreso"].satisfied and via_payslip["evidencia_ingreso"].satisfying_document_ids == [payslip_id]
    assert via_calc["evidencia_ingreso"].satisfied
    assert not neither["evidencia_ingreso"].satisfied


def test_accepted_document_types_restrict_the_alternatives():
    d = ProcessProfileDefinition(
        semantic_catalog_version=1,
        checklist=[ChecklistItem(key="i", label="i", requires_attributes=["ingreso.neto_mensual"], accepted_document_types=["payslip"])],
    )
    calc_only = _outcomes(d, [], [DocumentExtraction(document_id=uuid.uuid4(), document_type="debt_capacity_calculation", payload={"net_income": _env(1.0)})])
    assert not calc_only["i"].satisfied


def test_conditional_requirement_follows_the_process_data():
    d = convenios_definition()
    assert not _outcomes(d, [], request={"nacionalidad": "PE"})["carne_extranjeria"].applicable
    foreign = _outcomes(d, [], request={"nacionalidad": "VE"})["carne_extranjeria"]
    assert foreign.applicable and not foreign.satisfied


def test_unevaluable_condition_fails_closed():
    d = ProcessProfileDefinition(
        semantic_catalog_version=1,
        checklist=[ChecklistItem(key="x", label="x", document_type="payslip", required_when_cel="request.monto > 1000")],
    )
    outcome = _outcomes(d, [], request={})["x"]  # `monto` missing → evaluation error
    assert outcome.applicable and not outcome.satisfied and "se exige por seguridad" in (outcome.note or "")


def test_optional_requirement_never_applies():
    d = ProcessProfileDefinition(semantic_catalog_version=1, checklist=[ChecklistItem(key="x", label="x", document_type="payslip", required=False)])
    assert not _outcomes(d, [])["x"].applicable


# --- verdict ---------------------------------------------------------------


def test_no_reasons_means_continue():
    assert decide(VerdictInputs(), convenios_definition()).decision == "continue"


def test_missing_requirement_returns_to_client_and_wins_over_review():
    doc = uuid.uuid4()
    v = decide(
        VerdictInputs(open_conditions=[OpenCondition(key="sol", label="Solicitud", kind="missing_document")], pending_review_document_ids={doc}),
        convenios_definition(),
    )
    assert v.decision == "return_to_client"
    assert {r.kind for r in v.reasons} == {"missing_document", "pending_review"}  # every reason is reported


def test_blocking_binding_uses_its_on_fail_and_non_blocking_does_not_decide():
    d = ProcessProfileDefinition(
        semantic_catalog_version=1,
        rule_bindings=[
            RuleBinding(rule_id="a", severity=Severity.ERROR, blocking=True, on_fail="return_to_client"),
            RuleBinding(rule_id="b", severity=Severity.WARNING),
        ],
    )
    assert decide(VerdictInputs(findings=[FindingInput("b", "x", None)]), d).decision == "continue"
    assert decide(VerdictInputs(findings=[FindingInput("a", "x", None)]), d).decision == "return_to_client"


def test_a_finding_with_several_lines_gives_one_reason_per_line():
    d = ProcessProfileDefinition(semantic_catalog_version=1, rule_bindings=[RuleBinding(rule_id="a", blocking=True, on_fail="human_review")])
    reasons = decide(VerdictInputs(findings=[FindingInput("a", "DNI no coincide.\nPlazo no coincide.", None)]), d).reasons
    assert [r.message for r in reasons] == ["DNI no coincide.", "Plazo no coincide."]


def test_failed_document_needs_human_review():
    assert decide(VerdictInputs(failed_document_ids={uuid.uuid4()}), None).decision == "human_review"


def test_without_profile_findings_never_block():
    assert decide(VerdictInputs(findings=[FindingInput("semantic.attribute_consistency", "x", None)]), None).decision == "continue"


# --- profile → rules -------------------------------------------------------


def test_only_bound_rules_run_unless_profile_includes_all():
    rules = [SemanticAttributeConsistency(), PayslipArithmeticConsistency()]
    only_semantic = ProcessProfileDefinition(semantic_catalog_version=1, rule_bindings=[RuleBinding(rule_id="semantic.attribute_consistency")])
    assert [r.rule_id for r in rules_for_profile(rules, only_semantic)] == ["semantic.attribute_consistency"]
    assert rules_for_profile(rules, ProcessProfileDefinition(semantic_catalog_version=1, include_all_rules=True)) == rules
    assert rules_for_profile(rules, None) == rules


def test_binding_severity_overrides_the_rule_default():
    failed = ValidationResult(
        rule_id="semantic.attribute_consistency",
        category=RuleCategory.CROSS_DOCUMENT,
        passed=False,
        severity=Severity.WARNING,
        message="x",
        confidence=1.0,
        confidence_method=ConfidenceMethod.FUZZY_DETERMINISTIC,
        explanation="x",
    )
    assert apply_binding(failed, convenios_definition()).severity == Severity.ERROR
    assert apply_binding(failed, None).severity == Severity.WARNING
