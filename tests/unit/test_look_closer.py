"""VRT-113: the agent can look at the page where the OCR may have lost a
value, and a value that is nowhere in the text read goes to a person."""

from __future__ import annotations

import base64
import io

from PIL import Image

from idp.domain.document_type_catalog import compile_schema
from idp.domain.document_type_seed import seed_definitions
from idp.extraction.agentic.tools import _beside_b64, region_tools
from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.review.routing import find_review_candidates

PAYSLIP = compile_schema(next(d for d in seed_definitions() if d.key == "payslip"))


def _page_b64(width: int = 400, height: int = 600) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _parsed() -> ParsedDocument:
    return ParsedDocument(
        backend="test",
        page_count=1,
        blocks=[ParsedBlock(region_id=61, text="LIQ S/.", page=0, bbox=[0.7, 0.80, 0.8, 0.83], confidence=0.9)],
        page_images_b64={0: _page_b64()},
    )


def test_looking_closer_shows_from_the_label_to_the_right_enlarged():
    """Nothing left of the label: a value printed there belongs to another label."""
    band = Image.open(io.BytesIO(base64.b64decode(_beside_b64(_parsed(), "LIQ S/.") or "")))
    assert band.width == 2 * (400 - int(0.68 * 400))  # from just before the label to the right edge, twice as large
    assert 0 < band.height < 600


def test_a_label_not_in_the_text_has_nothing_to_show():
    assert _beside_b64(_parsed(), "NETO A PAGAR") is None


def test_the_agent_has_the_tools_to_look():
    assert {"look_closer", "look_at_page"} <= {t.name for t in region_tools(_parsed())}


def _env(value, page: int | None = 0) -> dict:
    return {"value": value, "confidence": 0.95, "source_text": str(value), "page": page}


def _payslip(net_pay_page: int | None) -> dict:
    return {
        "employee_name": _env("SALAS SIGUAS, KATERIN KAROLA"),
        "period": _env("ENERO - 2026"),
        "gross_pay": _env(6618.0),
        "total_deductions": _env(2313.86),
        "net_pay": _env(4304.14, page=net_pay_page),
        "concepts": [{"name": _env("SUELDO"), "amount": _env(6618.0), "kind": _env("earning", page=None)}],
        "summary": _env("Boleta de pago de enero.", page=None),
    }


def test_a_value_nowhere_in_the_text_read_goes_to_a_person():
    candidates = find_review_candidates(PAYSLIP.model_validate(_payslip(net_pay_page=None)), [], confidence_threshold=0.75)
    assert [(c.field_path, c.reason) for c in candidates] == [("net_pay", "not_in_text")]


def test_inferred_fields_and_located_values_do_not():
    """A concept's kind and the summary are the model's by design; every other value was found in the text."""
    assert find_review_candidates(PAYSLIP.model_validate(_payslip(net_pay_page=0)), [], confidence_threshold=0.75) == []
