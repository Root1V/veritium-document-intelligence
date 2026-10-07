"""Unit tests for process profiles (VRT-24): intrinsic validation of a
definition, cross-reference validation against the semantic catalog, the
known document types and rule ids, and the seed profiles. No DB, no LLM."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from idp.config import Settings
from idp.domain.document_types import DocumentType
from idp.domain.process_profile import ChecklistItem, ProcessProfileDefinition, RuleBinding, cross_reference_errors
from idp.domain.process_profile_seed import SEED_PROFILES, convenios_definition
from idp.domain.semantic_seed import seed_catalog
from idp.pipeline.orchestrator import hardcoded_rule_metadata
from idp.validation.base import Severity
from idp.validation.cel import compile_expression, evaluate

KNOWN_TYPES = {t.value for t in DocumentType}


def _known_rules() -> set[str]:
    return {rule_id for rule_id, _, _ in hardcoded_rule_metadata(Settings(_env_file=None))}


def _errors(definition: ProcessProfileDefinition) -> list[str]:
    return cross_reference_errors(definition, catalog=seed_catalog(), known_document_types=KNOWN_TYPES, known_rule_ids=_known_rules())


def _definition(**overrides) -> ProcessProfileDefinition:
    base: dict = dict(semantic_catalog_version=1)
    base.update(overrides)
    return ProcessProfileDefinition(**base)


# --- seeds -----------------------------------------------------------------


@pytest.mark.parametrize("key,build", [(key, build) for key, _, _, build in SEED_PROFILES])
def test_seed_profiles_reference_only_things_that_exist(key, build):
    assert _errors(build()) == [], key


def test_convenios_conditional_requirement_reads_the_process_data():
    item = next(i for i in convenios_definition().checklist if i.key == "carne_extranjeria")
    assert item.required_when_cel is not None
    program = compile_expression(item.required_when_cel)

    def applies(request: dict) -> bool:
        return bool(evaluate(program, {"request": request, "case": {}}))

    assert applies({"nacionalidad": "VE"})
    assert not applies({"nacionalidad": "PE"})
    assert not applies({})  # not stated → not required


# --- intrinsic validation --------------------------------------------------


def test_requirement_must_be_by_type_or_by_attribute_not_both():
    with pytest.raises(ValidationError, match="no ambos ni ninguno"):
        ChecklistItem(key="x", label="x", document_type="payslip", requires_attributes=["ingreso.neto_mensual"])
    with pytest.raises(ValidationError, match="no ambos ni ninguno"):
        ChecklistItem(key="x", label="x")


def test_accepted_document_types_only_on_attribute_requirements():
    with pytest.raises(ValidationError, match="accepted_document_types"):
        ChecklistItem(key="x", label="x", document_type="payslip", accepted_document_types=["payslip"])


def test_duplicate_requirement_keys_and_rule_bindings_are_rejected():
    with pytest.raises(ValidationError, match="requisito duplicado"):
        _definition(checklist=[ChecklistItem(key="a", label="a", document_type="payslip"), ChecklistItem(key="a", label="b", document_type="payslip")])
    with pytest.raises(ValidationError, match="regla vinculada dos veces"):
        _definition(rule_bindings=[RuleBinding(rule_id="r"), RuleBinding(rule_id="r")])


def test_invalid_required_when_cel_is_rejected():
    with pytest.raises(ValidationError, match="required_when_cel no compila"):
        _definition(checklist=[ChecklistItem(key="a", label="a", document_type="payslip", required_when_cel="request.x ==")])


# --- cross references ------------------------------------------------------


def test_unknown_document_type_attribute_role_and_rule_are_reported():
    errors = _errors(
        _definition(
            checklist=[
                ChecklistItem(key="a", label="a", document_type="pasaporte"),
                ChecklistItem(key="b", label="b", requires_attributes=["ingreso.anual"]),
                ChecklistItem(key="c", label="c", requires_attributes=["persona.dni"], role="garante"),
            ],
            rule_bindings=[RuleBinding(rule_id="no.existe")],
        )
    )
    assert any("'pasaporte'" in e for e in errors)
    assert any("'ingreso.anual'" in e for e in errors)
    assert any("'garante'" in e for e in errors)
    assert any("'no.existe'" in e for e in errors)


def test_attribute_requirement_restricted_to_types_that_dont_map_it_is_unsatisfiable():
    errors = _errors(
        _definition(
            checklist=[ChecklistItem(key="ingreso", label="i", requires_attributes=["ingreso.neto_mensual"], accepted_document_types=["insurance_disclosure"])]
        )
    )
    assert any("nunca se podría satisfacer" in e for e in errors)


def test_attribute_requirement_accepts_any_mapping_type_by_default():
    assert _errors(_definition(checklist=[ChecklistItem(key="ingreso", label="i", requires_attributes=["ingreso.neto_mensual"])])) == []


# --- identity --------------------------------------------------------------


def test_content_hash_changes_when_a_binding_severity_changes():
    a = _definition(rule_bindings=[RuleBinding(rule_id="semantic.attribute_consistency", severity=Severity.WARNING)])
    b = _definition(rule_bindings=[RuleBinding(rule_id="semantic.attribute_consistency", severity=Severity.ERROR)])
    assert a.content_hash() != b.content_hash()
    assert a.content_hash() == _definition(rule_bindings=[RuleBinding(rule_id="semantic.attribute_consistency", severity=Severity.WARNING)]).content_hash()


def test_binding_lookup():
    d = convenios_definition()
    binding = d.binding_for("semantic.attribute_consistency")
    assert binding is not None and binding.blocking and binding.severity == Severity.ERROR
    assert d.binding_for("no.existe") is None
