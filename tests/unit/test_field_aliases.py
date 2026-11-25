"""VRT-119: other names a field is printed under, and its format — sent to the
model — and the names recent documents print, found beside each value."""

from __future__ import annotations

from idp.domain.document_type_catalog import FieldSpec, compile_schema
from idp.domain.document_type_seed import seed_definitions
from idp.extraction.label_suggestions import label_of, suggest_labels
from idp.parsing.normalize import ParsedBlock, ParsedDocument

PAYSLIP = next(d for d in seed_definitions() if d.key == "payslip")


def _with(definition, **hints):
    return definition.model_copy(update={"fields": [f.model_copy(update=hints) if f.name == "net_pay" else f for f in definition.fields]})


def test_the_model_reads_the_other_names_and_the_format():
    schema = compile_schema(_with(PAYSLIP, aliases=["LIQ S/", "Neto"], format="number with 2 decimals"), for_agent=True).model_json_schema()
    described = schema["properties"]["net_pay"]["description"]
    assert "Also printed as: 'LIQ S/', 'Neto'." in described and described.endswith("Format: number with 2 decimals.")


def test_a_version_without_them_keeps_its_hash():
    assert _with(PAYSLIP, aliases=[]).content_hash() == PAYSLIP.content_hash()
    assert _with(PAYSLIP, aliases=["LIQ S/"]).content_hash() != PAYSLIP.content_hash()


def test_empty_and_repeated_names_are_dropped():
    assert FieldSpec(name="x", type="str", aliases=[" Ref. ", "", "Ref."]).aliases == ["Ref."]


def _block(i, text, bbox, page=0):
    return ParsedBlock(region_id=i, text=text, page=page, bbox=bbox, confidence=0.99)


LABEL, VALUE, ABOVE = _block(1, "LIQ S/", [0.10, 0.50, 0.20, 0.52]), _block(2, "4 304,14", [0.30, 0.50, 0.40, 0.52]), _block(3, "Ref:", [0.30, 0.45, 0.35, 0.47])


def test_the_label_is_beside_the_value_or_above_it_or_before_its_colon():
    parsed = ParsedDocument(backend="t", page_count=1, blocks=[LABEL, VALUE, ABOVE])
    assert label_of(VALUE, parsed) == "LIQ S/"
    assert label_of(VALUE, ParsedDocument(backend="t", page_count=1, blocks=[VALUE, ABOVE])) == "Ref"
    assert label_of(_block(4, "MONTO SOLICITADO: S/ 32 500", [0, 0, 1, 0.1]), parsed) == "MONTO SOLICITADO"


def _reading(net_label: str):
    parsed = ParsedDocument(backend="t", page_count=1, blocks=[_block(1, net_label, LABEL.bbox), VALUE])
    return {"net_pay": {"value": 4304.14, "page": 0, "bbox": VALUE.bbox}, "employee_name": {"value": net_label, "page": None, "bbox": None}}, parsed


def test_it_suggests_what_two_documents_print_and_the_field_does_not_know():
    readings = [_reading("LIQ S/"), _reading("LIQ S/"), _reading("NETO A PAGAR")]
    assert [(s.field, s.label, s.documents) for s in suggest_labels(readings[:2] + readings[2:], {})] == [], "a label that is a value of the document is not one"
    readings = [({**p, "employee_name": {"value": "ANA", "page": None, "bbox": None}}, parsed) for p, parsed in readings]
    assert [(s.field, s.label, s.documents) for s in suggest_labels(readings, {})] == [("net_pay", "LIQ S/", 2)]
    assert suggest_labels(readings, {"net_pay": ["liq s/"]}) == []
