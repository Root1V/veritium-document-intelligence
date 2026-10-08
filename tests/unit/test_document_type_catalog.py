"""Unit tests for VRT-32: document types as versioned data. The seed must
reproduce the code schemas exactly (same JSON schema, so the same prompt and
the same validation), definitions reject what cannot compile into an
extraction schema, and a run sees the right version of each type."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from idp.api.routes.document_types import unmapped_paths
from idp.classification.classifier import _result_model
from idp.domain.document_type_catalog import DocumentTypeCatalog, DocumentTypeDefinition, compile_schema
from idp.domain.document_type_seed import seed_definitions
from idp.domain.document_types import DocumentType
from idp.domain.schemas import SCHEMA_BY_DOCUMENT_TYPE
from idp.domain.semantic_seed import seed_catalog
from idp.pipeline.orchestrator import _extraction_schema


def _definition(**fields_and_overrides) -> DocumentTypeDefinition:
    base = {"key": "recibo_luz", "display_name": "Recibo de luz", "description": "Recibo de servicio eléctrico", "schema_title": "ReciboLuzSchema",
            "fields": [{"name": "titular", "type": "str", "required": True}]}
    return DocumentTypeDefinition.model_validate(base | fields_and_overrides)


@pytest.mark.parametrize("definition", seed_definitions(), ids=lambda d: d.key)
def test_the_seed_compiles_to_exactly_the_code_schema(definition):
    assert compile_schema(definition).model_json_schema() == SCHEMA_BY_DOCUMENT_TYPE[DocumentType(definition.key)].model_json_schema()


def test_the_seed_covers_every_typed_document_with_texts():
    seed = {d.key: d for d in seed_definitions()}
    assert set(seed) == {t.value for t in DocumentType} - {"generic"}
    assert all(d.display_name and d.description and d.extraction_hint for d in seed.values())


def test_a_compiled_schema_validates_like_an_extraction():
    model = compile_schema(_definition(fields=[
        {"name": "titular", "type": "str", "required": True, "description": "Nombre del titular"},
        {"name": "tarifa", "type": "enum", "enum_values": ["BT5B", "BT6"]},
        {"name": "lineas", "type": "list", "item_name": "Linea", "items": [{"name": "monto", "type": "float", "required": True}]},
    ]))
    ok = model.model_validate({"titular": {"value": "ANA", "confidence": 0.9}, "tarifa": {"value": "BT5B", "confidence": 0.8},
                               "lineas": [{"monto": {"value": 10.5, "confidence": 0.9}}]})
    assert ok.titular.value == "ANA" and ok.lineas[0].monto.value == 10.5
    with pytest.raises(ValidationError):
        model.model_validate({"titular": {"value": "ANA", "confidence": 0.9}, "tarifa": {"value": "OTRA", "confidence": 0.8}})
    with pytest.raises(ValidationError):
        model.model_validate({})  # titular is required


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"key": "generic"}, "reservada"),
        ({"key": "Recibo"}, "snake_case"),
        ({"fields": [{"name": "a", "type": "str"}, {"name": "a", "type": "int"}]}, "repetidos"),
        ({"fields": [{"name": "t", "type": "enum"}]}, "enum_values"),
        ({"fields": [{"name": "l", "type": "list", "item_name": "L", "required": True, "items": [{"name": "x", "type": "str"}]}]}, "obligatoria"),
        ({"fields": [{"name": "l", "type": "list", "item_name": "L", "items": [{"name": "m", "type": "list", "item_name": "M", "items": [{"name": "x", "type": "str"}]}]}]}, "un nivel"),
        ({"fields": []}, "al menos un campo"),
    ],
)
def test_definitions_reject_what_cannot_be_an_extraction_schema(override, message):
    with pytest.raises(ValidationError, match=message):
        _definition(**override)


def test_a_run_sees_the_latest_published_version_and_can_reread_older_ones():
    v1 = _definition()
    v2 = _definition(fields=[{"name": "titular", "type": "str", "required": True}, {"name": "monto", "type": "float"}])
    catalog = DocumentTypeCatalog([("recibo_luz", 1, "retired", v1), ("recibo_luz", 2, "published", v2)])
    assert catalog.keys() == ["recibo_luz"] and catalog.current("recibo_luz")[0] == 2
    assert "monto" not in catalog.schema("recibo_luz", 1).model_fields  # the old payloads re-read with their schema
    assert _extraction_schema(catalog, "recibo_luz", "2") is catalog.schema("recibo_luz", 2)


def test_extractions_from_before_the_catalog_are_version_one():
    catalog = DocumentTypeCatalog([(d.key, 1, "published", d) for d in seed_definitions()])
    assert _extraction_schema(catalog, "payslip", "1.0").model_json_schema() == SCHEMA_BY_DOCUMENT_TYPE[DocumentType.PAYSLIP].model_json_schema()


def test_the_classifier_can_only_answer_a_published_type_or_generic():
    model = _result_model(("payslip", "recibo_luz"))
    assert model.model_validate({"document_type": "recibo_luz", "confidence": 0.9, "reasoning": "x"}).document_type == "recibo_luz"
    assert model.model_validate({"document_type": "generic", "confidence": 0.9, "reasoning": "x"})
    with pytest.raises(ValidationError):
        model.model_validate({"document_type": "factura", "confidence": 0.9, "reasoning": "x"})


def test_publishing_a_schema_that_drops_a_semantically_mapped_field_is_caught():
    payslip = next(d for d in seed_definitions() if d.key == "payslip")
    assert unmapped_paths(payslip, seed_catalog()) == []
    without_net = payslip.model_copy(update={"fields": [f for f in payslip.fields if f.name != "net_pay"]})
    assert unmapped_paths(without_net, seed_catalog()) == ["net_pay"]
