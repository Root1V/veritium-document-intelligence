from idp.domain.document_type_seed import seed_definitions
from idp.domain.semantic_seed import seed_catalog
from idp.review.labels import describe_field

PAYSLIP = next(d for d in seed_definitions() if d.key == "payslip")


def test_mapped_field_reads_as_its_semantic_attribute_and_role() -> None:
    label = describe_field(
        "employee_code",
        document_type="payslip",
        definition=PAYSLIP,
        catalog=seed_catalog(),
        payload=None,
    )
    assert label.label == "Código de empleado"
    assert label.role == "Titular"
    assert label.attribute == "persona.codigo_empleado"
    assert label.description


def test_unmapped_field_falls_back_to_the_type_field() -> None:
    label = describe_field(
        "period",
        document_type="payslip",
        definition=PAYSLIP,
        catalog=seed_catalog(),
        payload=None,
    )
    assert label.label == "Period"
    assert label.attribute is None


def test_list_item_names_the_item_and_its_position() -> None:
    label = describe_field(
        "concepts[2].amount",
        document_type="payslip",
        definition=PAYSLIP,
        catalog=seed_catalog(),
        payload=None,
    )
    assert label.label == "Amount — concepts #3"
    assert label.description == PAYSLIP.fields[[f.name for f in PAYSLIP.fields].index("concepts")].item_description


def test_generic_field_uses_the_key_the_extraction_gave_it() -> None:
    payload = {"fields": [{"key": "person_2_estado_civil", "value": {"value": "C", "confidence": 0.6}}]}
    label = describe_field(
        "fields[0].value",
        document_type="generic",
        definition=None,
        catalog=seed_catalog(),
        payload=payload,
    )
    assert label.label == "Person 2 estado civil"


def test_generic_field_without_payload_still_reads_as_a_field() -> None:
    label = describe_field(
        "fields[4].value",
        document_type="generic",
        definition=None,
        catalog=None,
        payload=None,
    )
    assert label.label == "Campo 5"
