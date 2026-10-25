"""Unit tests for VRT-88: how people read each field of a document type."""

from __future__ import annotations

from idp.domain.document_type_seed import seed_definitions
from idp.domain.field_labels import labeled
from idp.review.labels import describe_field


def _payslip():
    return next(d for d in seed_definitions() if d.key == "payslip")


def test_a_label_is_not_a_new_version() -> None:
    definition = _payslip()
    assert labeled(definition).content_hash() == definition.content_hash()


def test_the_table_names_fields_without_overriding_a_label_set_on_the_type() -> None:
    definition = _payslip()
    definition.fields[0].label = "Trabajador"
    named = labeled(definition)
    assert named.fields[0].label == "Trabajador"
    assert next(f for f in named.fields if f.name == "net_pay").label == "Neto a pagar"
    concepts = next(f for f in named.fields if f.name == "concepts")
    assert concepts.label == "Conceptos" and concepts.items and concepts.items[0].label == "Concepto"


def test_every_field_of_the_built_in_types_has_a_name() -> None:
    for definition in map(labeled, seed_definitions()):
        unnamed = [f.name for f in definition.fields if not f.label] + [
            f"{f.name}[].{i.name}" for f in definition.fields for i in f.items or [] if not i.label
        ]
        assert not unnamed, f"{definition.key}: {unnamed}"


def test_review_reads_the_label() -> None:
    definition = labeled(_payslip())
    assert describe_field("employee_code", document_type="payslip", definition=definition, catalog=None, payload=None).label == "Código de trabajador"
    row = describe_field("concepts[1].amount", document_type="payslip", definition=definition, catalog=None, payload=None)
    assert row.label == "Monto — conceptos #2"
