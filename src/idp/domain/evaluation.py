"""Evaluation suites (VRT-42), the pure part: reading a table of expected
values, comparing an extracted value with an expected one by the field's
type, and the metrics of a run and the difference between two runs. The
runner (evaluation/runner.py) does the I/O."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from idp.domain.document_type_catalog import DocumentTypeCatalog, FieldSpec

# Columns of the table that are not field values.
FILE_COLUMN, TYPE_COLUMN, PAGES_COLUMN = "archivo", "tipo", "paginas"
_PAGES = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


# The template's example row: a file name that asks to be replaced, and a
# plausible value per field so the expected format is evident.
EXAMPLE_FILE = "EJEMPLO-reemplazar-o-borrar.pdf"
_EXAMPLES = (  # most specific words first
    (("dni",), "12345678"),
    (("ruc",), "20123456789"),
    (("birth", "nacimiento"), "1990-05-14"),
    (("date", "fecha"), "2026-01-31"),
    (("phone", "telefono", "celular"), "987654321"),
    (("address", "direccion"), "AV. EJEMPLO 123"),
    (("rate", "tasa"), "12.5%"),
    (("period", "periodo"), "01/2026"),
    (("employer", "empleador", "insurer", "aseguradora", "pension_fund", "afp", "bank", "banco", "company", "empresa"), "EMPRESA EJEMPLO S.A.C."),
    (("first_name", "nombres"), "ANA MARIA"),
    (("paternal",), "PEREZ"),
    (("maternal",), "ROJAS"),
    (("name", "nombre"), "PEREZ ROJAS, ANA MARIA"),
    (("code", "codigo", "number", "numero"), "011858"),
    (("email", "correo"), "ana.perez@ejemplo.pe"),
    (("place", "lugar", "city", "ciudad", "district", "distrito", "province", "provincia", "department", "departamento"), "LIMA"),
)
_AMOUNTS = ((("gross", "bruto"), "6618.00"), (("deduction", "descuento"), "2313.86"), (("net", "neto"), "4304.14"))


def example_value(spec: FieldSpec) -> str:
    if spec.type == "float":
        return next((value for words, value in _AMOUNTS if any(w in spec.name for w in words)), "15000.00")
    if spec.type == "int":
        return "12"
    if spec.type == "bool":
        return "sí"
    if spec.type == "enum" and spec.enum_values:
        return spec.enum_values[0]
    return next((value for words, value in _EXAMPLES if any(w in spec.name for w in words)), "texto tal como aparece")


def template_rows(document_type: str, fields: list[FieldSpec]) -> list[list[str]]:
    """Header and one example row for a type's evaluation table."""
    columns = [f for f in fields if f.type != "list"]
    return [
        [FILE_COLUMN, TYPE_COLUMN, PAGES_COLUMN, *(f.name for f in columns)],
        [EXAMPLE_FILE, document_type, "1", *(example_value(f) for f in columns)],
    ]


class CaseSpec(BaseModel):
    filename: str
    expected_document_type: str | None
    expected_fields: dict[str, Any]
    page_start: int | None = None  # 0-based, inclusive
    page_end: int | None = None


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _cell(value: Any) -> Any:
    # Excel stores 4304 as 4304.0; a code typed as a number loses nothing else.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value.strip() if isinstance(value, str) else value


def parse_table(rows: list[dict[str, Any]], catalog: DocumentTypeCatalog) -> tuple[list[CaseSpec], list[str]]:
    """Cases from the rows of a CSV/Excel table: ``archivo``, optional
    ``tipo`` and ``paginas`` ("1" or "1-3", 1-based), and one column per
    field. A blank cell is a field not evaluated. Returns the cases and the
    problems, row by row; a table with problems is not imported."""
    cases: list[CaseSpec] = []
    errors: list[str] = []
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        row = {str(k).strip().lower(): _cell(v) for k, v in row.items() if k is not None}
        if all(_blank(v) for v in row.values()):
            continue
        filename = row.pop(FILE_COLUMN, None)
        document_type = row.pop(TYPE_COLUMN, None) or None
        pages = row.pop(PAGES_COLUMN, None)
        fields = {k: v for k, v in row.items() if not _blank(v)}
        if _blank(filename):
            errors.append(f"fila {number}: falta '{FILE_COLUMN}'")
            continue
        page_start = page_end = None
        if not _blank(pages):
            match = _PAGES.match(str(pages))
            if match is None:
                errors.append(f"fila {number}: '{PAGES_COLUMN}' debe ser '2' o '1-3'")
                continue
            page_start = int(match.group(1)) - 1
            page_end = int(match.group(2) or match.group(1)) - 1
        if fields and document_type is None:
            errors.append(f"fila {number}: hay valores esperados pero falta '{TYPE_COLUMN}'")
            continue
        if document_type is not None:
            current = catalog.current(document_type)
            if current is None:
                errors.append(f"fila {number}: el tipo '{document_type}' no está en el catálogo")
                continue
            known = {f.name for f in current[1].fields if f.type != "list"}
            if unknown := sorted(set(fields) - known):
                errors.append(f"fila {number}: '{document_type}' no tiene los campos {', '.join(unknown)}")
                continue
        cases.append(
            CaseSpec(filename=str(filename), expected_document_type=document_type, expected_fields=fields, page_start=page_start, page_end=page_end)
        )
    if not cases and not errors:
        errors.append("la tabla no tiene filas")
    return cases, errors


def _text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().strip(" :;,.-").split())


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("S/", "").replace("$", "")
    if "," in text and "." in text:
        text = text.replace(",", "")  # 4,304.14
    elif re.fullmatch(r"-?\d+,\d{1,2}", text):
        text = text.replace(",", ".")  # 4304,14
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


_TRUE, _FALSE = {"true", "si", "sí", "1", "yes", "verdadero"}, {"false", "no", "0", "falso"}


def matches(spec: FieldSpec | None, expected: Any, actual: Any) -> bool:
    """Whether an extracted value is the expected one: numbers within a
    cent, booleans by meaning, everything else as text ignoring case,
    accents, spacing and edge punctuation."""
    if actual is None or actual == "":
        return False
    kind = spec.type if spec is not None else "str"
    if kind in ("int", "float"):
        e, a = _number(expected), _number(actual)
        return e is not None and a is not None and abs(e - a) < 0.011
    if kind == "bool":
        e, a = _text(expected), _text(actual)
        return (e in _TRUE and a in _TRUE) or (e in _FALSE and a in _FALSE)
    return _text(expected) == _text(actual)


class FieldResult(BaseModel):
    field: str
    expected: Any
    actual: Any
    confidence: float | None
    match: bool


def compare_fields(fields: list[FieldSpec], expected: dict[str, Any], payload: dict[str, Any] | None) -> list[FieldResult]:
    by_name = {f.name: f for f in fields}
    results = []
    for name, value in expected.items():
        envelope = (payload or {}).get(name)
        actual = envelope.get("value") if isinstance(envelope, dict) else envelope
        confidence = envelope.get("confidence") if isinstance(envelope, dict) else None
        results.append(FieldResult(field=name, expected=value, actual=actual, confidence=confidence, match=matches(by_name.get(name), value, actual)))
    return results


class CaseOutcome(BaseModel):
    """What the runner saw for one case — the input to the metrics."""

    case_id: str
    expected_document_type: str | None
    predicted_document_type: str | None
    failed: bool
    fields: list[FieldResult]


def _rate(correct: int, evaluated: int) -> dict[str, Any]:
    return {"evaluated": evaluated, "correct": correct, "accuracy": round(correct / evaluated, 4) if evaluated else None}


def summarize(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    classified = [o for o in outcomes if o.expected_document_type is not None and not o.failed]
    fields = [(o, f) for o in outcomes if not o.failed for f in o.fields]
    by_field: dict[str, list[bool]] = defaultdict(list)
    for o, f in fields:
        by_field[f"{o.expected_document_type or o.predicted_document_type}.{f.field}"].append(f.match)
    return {
        "cases": len(outcomes),
        "failed": sum(o.failed for o in outcomes),
        "classification": _rate(sum(o.predicted_document_type == o.expected_document_type for o in classified), len(classified)),
        "fields": _rate(sum(f.match for _, f in fields), len(fields)),
        "by_field": {key: _rate(sum(v), len(v)) for key, v in sorted(by_field.items())},
    }


class Change(BaseModel):
    case_id: str
    field: str  # "tipo" for the classification
    expected: Any
    before: Any
    after: Any


class RunComparison(BaseModel):
    regressions: list[Change]
    improvements: list[Change]


def compare_runs(baseline: list[CaseOutcome], current: list[CaseOutcome]) -> RunComparison:
    """Field by field, over the cases both runs evaluated: what was right
    before and is wrong now (regressions), and the other way round."""
    before = {o.case_id: o for o in baseline if not o.failed}
    regressions: list[Change] = []
    improvements: list[Change] = []
    for o in current:
        b = before.get(o.case_id)
        if b is None or o.failed:
            continue
        if o.expected_document_type is not None:
            was, now = b.predicted_document_type == o.expected_document_type, o.predicted_document_type == o.expected_document_type
            if was != now:
                change = Change(case_id=o.case_id, field="tipo", expected=o.expected_document_type, before=b.predicted_document_type, after=o.predicted_document_type)
                (improvements if now else regressions).append(change)
        previous = {f.field: f for f in b.fields}
        for f in o.fields:
            p = previous.get(f.field)
            if p is not None and p.match != f.match:
                change = Change(case_id=o.case_id, field=f.field, expected=f.expected, before=p.actual, after=f.actual)
                (improvements if f.match else regressions).append(change)
    return RunComparison(regressions=regressions, improvements=improvements)
