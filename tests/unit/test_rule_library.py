"""Unit tests for VRT-36: a draft says AMBIGUA instead of guessing, comes
with test cases that a rule must pass before activation, and a rule over a
semantic attribute runs on every document that contributes the attribute."""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from idp.domain.rule_draft import RuleDraft, RuleTestCase
from idp.domain.semantic_resolution import DocumentExtraction, resolve_case
from idp.domain.semantic_seed import seed_catalog
from idp.persistence.models import ValidationRuleDefinition
from idp.validation.rules.generic import DataDrivenRule, run_test_cases
from tests.conftest import make_context, make_document_fields

MIN_INCOME = "value >= 1025.0"


def _case(name: str, value, expect: str) -> RuleTestCase:
    return RuleTestCase.model_validate({"name": name, "input": {"value": value}, "expect": expect})


def test_an_ambiguous_draft_carries_questions_and_no_rule():
    draft = RuleDraft(outcome="ambiguous", questions=["¿Cuál es el ingreso mínimo?"], rationale="Falta el umbral.")
    assert draft.condition_cel is None
    with pytest.raises(ValidationError, match="pregunta"):
        RuleDraft(outcome="ambiguous", rationale="x")


def test_a_usable_draft_needs_a_condition_and_a_passing_and_a_failing_case():
    with pytest.raises(ValidationError, match="'pass' y uno 'fail'"):
        RuleDraft(outcome="ok", condition_cel=MIN_INCOME, rationale="x", test_cases=[_case("alto", 3000, "pass")])
    draft = RuleDraft(outcome="ok", condition_cel=MIN_INCOME, rationale="x", test_cases=[_case("alto", 3000, "pass"), _case("bajo", 500, "fail")])
    assert draft.outcome == "ok"


def test_test_cases_run_the_rule_cel_with_the_same_variables():
    results = run_test_cases(MIN_INCOME, None, [_case("alto", 3000, "pass"), _case("bajo", 500, "fail"), _case("mal esperado", 500, "pass")], value_type="number")
    assert [(r.got, r.ok) for r in results] == [("pass", True), ("fail", True), ("fail", False)]


def test_a_case_where_the_rule_does_not_apply_passes_and_a_cel_error_is_reported():
    results = run_test_cases(MIN_INCOME, "request.convenio == 'X'", [RuleTestCase.model_validate({"name": "otro convenio", "input": {"value": 1, "request": {"convenio": "Y"}}, "expect": "pass"})])
    assert results[0].got == "pass"
    errored = run_test_cases("value.size() > 0", None, [_case("número", 5, "pass")])
    assert errored[0].got == "error" and errored[0].detail


def _rule() -> DataDrivenRule:
    return DataDrivenRule(ValidationRuleDefinition(
        kind="cel", rule_id="custom.ingreso.neto_mensual.min", category="self", attribute="ingreso.neto_mensual",
        condition_cel=MIN_INCOME, severity="error", message_pass="ok", message_fail="ingreso bajo", status="active", test_cases=[],
    ))


def _context(document_type: str, payload: dict):
    fields = make_document_fields(document_type, {k: v["value"] for k, v in payload.items()})
    view = resolve_case(seed_catalog(), [DocumentExtraction(document_id=fields.document_id, document_type=document_type, payload=payload)])
    return dataclasses.replace(make_context(fields), semantic_view=view)


@pytest.mark.asyncio
async def test_a_rule_over_an_attribute_runs_where_a_document_contributes_it():
    rule = _rule()
    low = _context("payslip", {"net_pay": {"value": 900.0, "confidence": 0.9}})
    assert rule.applies_when(low)
    result = await rule.evaluate(low)
    assert not result.passed and result.field_path == "net_pay"
    high = _context("payslip", {"net_pay": {"value": 4304.14, "confidence": 0.9}})
    assert (await rule.evaluate(high)).passed
    assert not rule.applies_when(_context("insurance_disclosure", {"insured_dni": {"value": "42785091", "confidence": 0.9}}))
