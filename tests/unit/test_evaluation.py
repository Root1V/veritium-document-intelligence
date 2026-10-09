"""Unit tests for VRT-42's pure part: reading a table of expected values,
comparing by field type, and the metrics and comparison of runs."""

from __future__ import annotations

from idp.domain.document_type_catalog import DocumentTypeCatalog, FieldSpec
from idp.domain.document_type_seed import seed_definitions
from idp.domain.evaluation import CaseOutcome, FieldResult, compare_fields, compare_runs, matches, parse_table, summarize

CATALOG = DocumentTypeCatalog([(d.key, 1, "published", d) for d in seed_definitions()])
PAYSLIP_FIELDS = next(d for d in seed_definitions() if d.key == "payslip").fields


def test_a_table_becomes_cases_with_pages_and_expected_fields() -> None:
    cases, errors = parse_table(
        [
            {"archivo": "boleta.png", "tipo": "payslip", "paginas": "", "net_pay": 4304.14, "employee_code": "011858", "period": ""},
            {"archivo": "paquete.pdf", "tipo": "payslip", "paginas": "2-3", "net_pay": "", "employee_code": "", "period": ""},
            {"archivo": "", "tipo": "", "paginas": "", "net_pay": "", "employee_code": "", "period": ""},  # blank row
        ],
        CATALOG,
    )
    assert errors == []
    assert cases[0].expected_fields == {"net_pay": 4304.14, "employee_code": "011858"}, "a blank cell is not evaluated"
    assert (cases[1].page_start, cases[1].page_end) == (1, 2), "pages are 1-based in the table, 0-based inside"
    assert len(cases) == 2


def test_a_table_with_problems_says_which_row() -> None:
    _, errors = parse_table(
        [
            {"archivo": "a.png", "tipo": "payslip", "sueldo": "100"},
            {"archivo": "b.png", "tipo": "no_existe"},
            {"archivo": "c.png", "net_pay": "100"},
            {"tipo": "payslip"},
            {"archivo": "d.png", "tipo": "payslip", "paginas": "dos"},
        ],
        CATALOG,
    )
    assert errors == [
        "fila 2: 'payslip' no tiene los campos sueldo",
        "fila 3: el tipo 'no_existe' no está en el catálogo",
        "fila 4: hay valores esperados pero falta 'tipo'",
        "fila 5: falta 'archivo'",
        "fila 6: 'paginas' debe ser '2' o '1-3'",
    ]


def test_values_match_by_the_field_type() -> None:
    money = FieldSpec(name="net_pay", type="float")
    assert matches(money, "4,304.14", 4304.14)
    assert matches(money, "4304,14", 4304.14)
    assert not matches(money, "4304.14", 4304.0)
    text = FieldSpec(name="employee_name", type="str")
    assert matches(text, "Salas Siguas, Katerín", ": SALAS SIGUAS, KATERIN ")
    assert not matches(text, "011858", "11858")
    assert matches(FieldSpec(name="flag", type="bool"), "sí", True)
    assert not matches(text, "x", None)


def test_fields_are_compared_against_the_extraction_envelopes() -> None:
    payload = {"net_pay": {"value": 4304.14, "confidence": 0.9}, "employee_code": {"value": "011859", "confidence": 0.4}}
    results = compare_fields(PAYSLIP_FIELDS, {"net_pay": "4304.14", "employee_code": "011858", "period": "01/2026"}, payload)
    assert [(r.field, r.match, r.confidence) for r in results] == [("net_pay", True, 0.9), ("employee_code", False, 0.4), ("period", False, None)]


def _outcome(case_id: str, predicted: str, **fields: tuple[object, bool]) -> CaseOutcome:
    return CaseOutcome(
        case_id=case_id,
        expected_document_type="payslip",
        predicted_document_type=predicted,
        failed=False,
        fields=[FieldResult(field=k, expected=e, actual=e if ok else "x", confidence=None, match=ok) for k, (e, ok) in fields.items()],
    )


def test_metrics_of_a_run() -> None:
    metrics = summarize(
        [
            _outcome("1", "payslip", net_pay=(1, True), period=("01", False)),
            _outcome("2", "generic", net_pay=(2, False)),
            CaseOutcome(case_id="3", expected_document_type="payslip", predicted_document_type=None, failed=True, fields=[]),
        ]
    )
    assert metrics["failed"] == 1
    assert metrics["classification"] == {"evaluated": 2, "correct": 1, "accuracy": 0.5}
    assert metrics["fields"] == {"evaluated": 3, "correct": 1, "accuracy": 0.3333}
    assert metrics["by_field"]["payslip.net_pay"] == {"evaluated": 2, "correct": 1, "accuracy": 0.5}


def test_comparing_runs_finds_regressions_and_improvements() -> None:
    before = [_outcome("1", "payslip", net_pay=(1, True), period=("01", False)), _outcome("2", "payslip", net_pay=(2, True))]
    after = [_outcome("1", "payslip", net_pay=(1, False), period=("01", True)), _outcome("2", "generic", net_pay=(2, True))]
    comparison = compare_runs(before, after)
    assert {(c.case_id, c.field) for c in comparison.regressions} == {("1", "net_pay"), ("2", "tipo")}
    assert {(c.case_id, c.field) for c in comparison.improvements} == {("1", "period")}
