"""Unit tests for VRT-35: an attribute's format, declared once in the
semantic catalog, is checked wherever a document maps a field to it; and a
published profile that bound the retired per-type DNI rules keeps its
behaviour through the rule that replaced them."""

from __future__ import annotations

import dataclasses

import pytest

from idp.domain.process_profile import ProcessProfileDefinition, RuleBinding
from idp.domain.semantic_resolution import DocumentExtraction, resolve_case
from idp.domain.semantic_seed import seed_catalog
from idp.pipeline.case_evaluation import rules_for_profile
from idp.validation.base import Severity
from idp.validation.rules.semantic_rules import format_rules
from tests.conftest import make_context, make_document_fields

DNI_RULE = "semantic.format.persona.dni"


def _context(document_type: str, payload: dict):
    fields = make_document_fields(document_type, {k: v["value"] for k, v in payload.items()})
    view = resolve_case(seed_catalog(), [DocumentExtraction(document_id=fields.document_id, document_type=document_type, payload=payload)])
    return dataclasses.replace(make_context(fields), semantic_view=view)


def _rule(rule_id: str):
    return next(r for r in format_rules(seed_catalog()) if r.rule_id == rule_id)


def test_one_rule_per_attribute_that_declares_a_format():
    assert {r.rule_id for r in format_rules(seed_catalog())} == {DNI_RULE, "semantic.format.empleador.ruc"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("document_type", "field"),
    [("insurance_disclosure", "insured_dni"), ("authorization_letter", "client_dni"), ("account_statement", "member_dni")],
)
async def test_the_dni_format_applies_to_any_type_that_maps_a_dni(document_type, field):
    rule = _rule(DNI_RULE)
    ok = _context(document_type, {field: {"value": "42785091", "confidence": 0.9}})
    assert rule.applies_when(ok) and (await rule.evaluate(ok)).passed
    bad = _context(document_type, {field: {"value": "abc123", "confidence": 0.9}})
    result = await rule.evaluate(bad)
    assert not result.passed and result.severity == Severity.ERROR and result.field_path == field and result.actual == ["abc123"]


@pytest.mark.asyncio
async def test_a_document_without_the_attribute_is_not_checked():
    rule = _rule(DNI_RULE)
    assert not rule.applies_when(_context("payslip", {"net_pay": {"value": 100.0, "confidence": 0.9}}))


def _legacy_profile() -> ProcessProfileDefinition:
    return ProcessProfileDefinition(
        semantic_catalog_version=1,
        rule_bindings=[
            RuleBinding(rule_id="self.loan_application_dni_format_valid", severity=Severity.ERROR, blocking=True, on_fail="human_review"),
            RuleBinding(rule_id="self.insurance_disclosure_dni_format_valid", severity=Severity.WARNING),
        ],
    )


def test_a_published_profile_bound_to_the_retired_dni_rules_keeps_its_check():
    profile = _legacy_profile()
    assert [r.rule_id for r in rules_for_profile(format_rules(seed_catalog()), profile)] == [DNI_RULE]
    binding = profile.binding_for(DNI_RULE)
    assert binding.severity == Severity.ERROR and binding.blocking and binding.on_fail == "human_review"  # the strictest one


def test_a_new_profile_version_cannot_bind_a_retired_id():
    from idp.domain.process_profile import cross_reference_errors

    errors = cross_reference_errors(_legacy_profile(), catalog=seed_catalog(), known_document_types=set(), known_rule_ids={DNI_RULE})
    assert any("self.loan_application_dni_format_valid" in e for e in errors)
