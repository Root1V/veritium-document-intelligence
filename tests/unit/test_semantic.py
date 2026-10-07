"""Unit tests for the semantic catalog (VRT-23): catalog integrity, the seed
mapped against the real schemas, per-case resolution, the generic
consistency rule, and the `case` CEL variable. No DB, no LLM."""

from __future__ import annotations

import typing
import uuid

import pytest
from pydantic import BaseModel, ValidationError

from idp.domain.schemas import SCHEMA_BY_DOCUMENT_TYPE
from idp.domain.semantic import FieldMapping, SemanticAttribute, SemanticCatalog, SemanticEntity, SemanticRole
from idp.domain.semantic_resolution import DocumentExtraction, resolve_case
from idp.domain.semantic_seed import seed_catalog
from idp.persistence.models import ValidationRuleDefinition
from idp.validation.rules.generic import DataDrivenRule
from idp.validation.rules.semantic_rules import SemanticAttributeConsistency
from tests.conftest import make_context, make_document_fields


def _env(value, *, page: int = 1, confidence: float = 0.9, bbox: list[float] | None = None) -> dict:
    return {"value": value, "page": page, "bbox": bbox or [0.1, 0.1, 0.2, 0.2], "confidence": confidence, "source_text": str(value)}


def _doc(document_type: str, payload: dict, document_id: uuid.UUID | None = None) -> DocumentExtraction:
    return DocumentExtraction(document_id=document_id or uuid.uuid4(), document_type=document_type, payload=payload)


# --- the seed against the real schemas ------------------------------------


def _field_exists(schema: type[BaseModel], path: str) -> bool:
    head, _, tail = path.partition(".")
    if "[" in head:
        list_field = head.split("[", 1)[0]
        if list_field not in schema.model_fields:
            return False
        item_type = typing.get_args(schema.model_fields[list_field].annotation)[0]
        return tail in item_type.model_fields
    return path in schema.model_fields


def test_seed_catalog_is_valid_and_every_mapping_points_at_a_real_schema_field():
    catalog = seed_catalog()
    schemas = {dt.value: cls for dt, cls in SCHEMA_BY_DOCUMENT_TYPE.items()}
    for mapping in catalog.mappings:
        assert mapping.document_type in schemas, mapping.document_type
        for path in mapping.field_paths:
            assert _field_exists(schemas[mapping.document_type], path), f"{mapping.document_type}.{path}"


def test_content_hash_is_stable_for_identical_content():
    assert seed_catalog().content_hash() == seed_catalog().content_hash()


# --- catalog integrity -----------------------------------------------------


def _catalog(**overrides) -> dict:
    base = dict(
        entities=[SemanticEntity(key="persona", name="Persona", definition="x")],
        attributes=[SemanticAttribute(key="persona.dni", name="DNI", definition="x", data_type="string", comparison="identifier")],
        roles=[SemanticRole(key="titular", name="Titular", definition="x")],
        mappings=[FieldMapping(document_type="payslip", field_path="employee_code", attribute="persona.dni", role="titular")],
    )
    base.update(overrides)
    return base


def test_mapping_to_unknown_attribute_is_rejected():
    bad = [FieldMapping(document_type="payslip", field_path="x", attribute="persona.ruc", role="titular")]
    with pytest.raises(ValidationError, match="atributo inexistente"):
        SemanticCatalog(**_catalog(mappings=bad))


def test_attribute_of_unknown_entity_is_rejected():
    bad = [SemanticAttribute(key="empresa.ruc", name="RUC", definition="x", data_type="string", comparison="identifier")]
    with pytest.raises(ValidationError, match="entidad inexistente"):
        SemanticCatalog(**_catalog(attributes=bad, mappings=[]))


def test_invalid_format_cel_is_rejected():
    bad = [SemanticAttribute(key="persona.dni", name="DNI", definition="x", data_type="string", comparison="identifier", format_cel="value.matches(")]
    with pytest.raises(ValidationError, match="format_cel no compila"):
        SemanticCatalog(**_catalog(attributes=bad))


def test_duplicate_mapping_target_is_rejected():
    twice = [
        FieldMapping(document_type="payslip", field_path="a", attribute="persona.dni", role="titular"),
        FieldMapping(document_type="payslip", field_path="b", attribute="persona.dni", role="titular"),
    ]
    with pytest.raises(ValidationError, match="mapea dos veces"):
        SemanticCatalog(**_catalog(mappings=twice))


def test_tolerance_only_allowed_on_numbers():
    bad = [SemanticAttribute(key="persona.dni", name="DNI", definition="x", data_type="string", comparison="identifier", tolerance=0.1)]
    with pytest.raises(ValidationError, match="tolerance"):
        SemanticCatalog(**_catalog(attributes=bad))


# --- resolution ------------------------------------------------------------


def test_same_dni_across_documents_is_consistent_even_with_formatting():
    view = resolve_case(
        seed_catalog(),
        [
            _doc("insurance_disclosure", {"insured_dni": _env("12.345.678")}),
            _doc("loan_application", {"applicant_dni": _env("12345678")}),
        ],
    )
    dni = view.get("titular", "persona.dni")
    assert dni is not None and dni.status == "consistent" and len(dni.sources) == 2


def test_different_dni_is_a_conflict_with_both_values_and_evidence():
    a, b = uuid.uuid4(), uuid.uuid4()
    view = resolve_case(
        seed_catalog(),
        [
            _doc("insurance_disclosure", {"insured_dni": _env("12345678", page=1)}, a),
            _doc("loan_application", {"applicant_dni": _env("87654321", page=3)}, b),
        ],
    )
    dni = view.get("titular", "persona.dni")
    assert dni is not None and dni.status == "conflict"
    assert sorted(dni.distinct_values) == ["12345678", "87654321"]
    assert {s.page for s in dni.sources} == {1, 3}
    assert [c.attribute for c in view.conflicts_involving(a)] == ["persona.dni"]


def test_single_source_attribute():
    view = resolve_case(seed_catalog(), [_doc("payslip", {"net_pay": _env(4304.14)})])
    net = view.get("titular", "ingreso.neto_mensual")
    assert net is not None and net.status == "single_source" and net.value == 4304.14


def test_split_name_parts_concatenate_and_match_a_full_name_fuzzily():
    view = resolve_case(
        seed_catalog(),
        [
            _doc("payslip", {"employee_name": _env("SANTIAGO PEREZ, VICTOR")}),
            _doc(
                "insurance_disclosure",
                {
                    "insured_first_name": _env("Víctor", confidence=0.95),
                    "insured_paternal_surname": _env("Santiago", confidence=0.8),
                    "insured_maternal_surname": _env("Pérez", confidence=0.9),
                },
            ),
        ],
    )
    name = view.get("titular", "persona.nombre_completo")
    assert name is not None and name.status == "consistent"
    concatenated = next(s for s in name.sources if s.document_type == "insurance_disclosure")
    assert concatenated.value == "Víctor Santiago Pérez"
    assert concatenated.confidence == 0.8  # the weakest part


def test_numbers_within_tolerance_are_consistent_and_outside_are_not():
    def net(other: float) -> str:
        view = resolve_case(
            seed_catalog(),
            [_doc("payslip", {"net_pay": _env(4304.14)}), _doc("debt_capacity_calculation", {"net_income": _env(other)})],
        )
        resolved = view.get("titular", "ingreso.neto_mensual")
        assert resolved is not None
        return resolved.status

    assert net(4300.00) == "consistent"  # 0.1% apart, tolerance 1%
    assert net(3900.00) == "conflict"


def test_dates_in_different_formats_are_consistent():
    view = resolve_case(
        seed_catalog(),
        [
            _doc("loan_application", {"date_of_birth": _env("15/03/1985")}),
            _doc("foreign_resident_id", {"persons": [{"date_of_birth": _env("1985-03-15")}]}),
        ],
    )
    born = view.get("titular", "persona.fecha_nacimiento")
    assert born is not None and born.status == "consistent"


def test_nested_list_path_is_read():
    view = resolve_case(seed_catalog(), [_doc("foreign_resident_id", {"persons": [{"foreigner_id_number": _env("001234567")}]})])
    ce = view.get("titular", "persona.carnet_extranjeria")
    assert ce is not None and ce.value == "001234567" and ce.sources[0].field_path == "persons[0].foreigner_id_number"


def test_roles_are_kept_apart():
    view = resolve_case(
        seed_catalog(),
        [
            _doc(
                "loan_application",
                {
                    "applicant_first_name": _env("Victor"),
                    "applicant_paternal_surname": _env("Santiago"),
                    "applicant_maternal_surname": _env("Perez"),
                    "loan_officer_name": _env("Ana Torres Ruiz"),
                },
            ),
            _doc("payslip", {"employee_name": _env("Victor Santiago Perez")}),
        ],
    )
    titular = view.get("titular", "persona.nombre_completo")
    asesor = view.get("asesor", "persona.nombre_completo")
    assert titular is not None and titular.status == "consistent"
    assert asesor is not None and asesor.status == "single_source"


def test_null_and_empty_values_are_ignored():
    view = resolve_case(seed_catalog(), [_doc("insurance_disclosure", {"insured_dni": None}), _doc("loan_application", {"applicant_dni": _env("")})])
    assert view.get("titular", "persona.dni") is None


def test_highest_confidence_source_wins_the_value():
    view = resolve_case(
        seed_catalog(),
        [
            _doc("insurance_disclosure", {"insured_dni": _env("11111111", confidence=0.4)}),
            _doc("loan_application", {"applicant_dni": _env("22222222", confidence=0.97)}),
        ],
    )
    dni = view.get("titular", "persona.dni")
    assert dni is not None and dni.value == "22222222"


def test_as_cel_is_nested_by_role_entity_and_name():
    view = resolve_case(seed_catalog(), [_doc("insurance_disclosure", {"insured_dni": _env("12345678")})])
    assert view.as_cel() == {"titular": {"persona": {"dni": "12345678"}}}


# --- the generic consistency rule ------------------------------------------


@pytest.mark.asyncio
async def test_consistency_rule_flags_only_documents_involved_in_a_conflict():
    insurance_id, loan_id, payslip_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    view = resolve_case(
        seed_catalog(),
        [
            _doc("insurance_disclosure", {"insured_dni": _env("12345678")}, insurance_id),
            _doc("loan_application", {"applicant_dni": _env("87654321")}, loan_id),
            _doc("payslip", {"net_pay": _env(100.0)}, payslip_id),
        ],
    )
    rule = SemanticAttributeConsistency()

    involved = make_context(make_document_fields("insurance_disclosure", {}, insurance_id))
    involved.semantic_view = view
    result = await rule.evaluate(involved)
    assert not result.passed and result.field_path == "titular.persona.dni"
    assert "12345678" in result.message and "87654321" in result.message

    bystander = make_context(make_document_fields("payslip", {}, payslip_id))
    bystander.semantic_view = view
    assert (await rule.evaluate(bystander)).passed


def test_consistency_rule_does_not_apply_without_a_semantic_view():
    assert not SemanticAttributeConsistency().applies_when(make_context(make_document_fields("payslip", {})))


# --- `case` in CEL ---------------------------------------------------------


@pytest.mark.asyncio
async def test_cel_rules_can_read_the_case_semantic_view():
    view = resolve_case(seed_catalog(), [_doc("payslip", {"net_pay": _env(4304.14)})])
    row = ValidationRuleDefinition(
        id=uuid.uuid4(),
        kind="cel",
        rule_id="custom.ingreso_minimo",
        category="self",
        document_type=None,
        field_path=None,
        condition_cel="case.titular.ingreso.neto_mensual >= 1500.0",
        applies_when_cel="has(case.titular)",
        severity="warning",
        message_pass="ok",
        message_fail="ingreso insuficiente",
        status="active",
    )
    context = make_context(make_document_fields("payslip", {"net_pay": 4304.14}))
    context.semantic_view = view
    rule = DataDrivenRule(row)
    assert rule.applies_when(context)
    assert (await rule.evaluate(context)).passed
