"""Unit tests for VRT-45's pure part: the documents as the model reads them,
citations resolved to their evidence, invented references and quotes
caught, and every playbook point answered."""

from __future__ import annotations

import uuid

import pytest

from idp.domain.lenses import (
    SEED_LENSES,
    ClauseAnswer,
    CitedPoint,
    LensDefinition,
    LensDocument,
    LensSummaryAnswer,
    PlaybookAnswer,
    build_output,
    render_context,
)
from idp.parsing.normalize import ParsedBlock, ParsedDocument

LETTER = uuid.uuid4()


def _doc(blocks: list[tuple[int, int, str]], **kw) -> LensDocument:
    parsed = ParsedDocument(
        backend="stub",
        page_count=3,
        blocks=[ParsedBlock(region_id=r, text=t, page=p, bbox=[0.1, 0.1, 0.2, 0.2], confidence=0.9) for r, p, t in blocks],
    )
    return LensDocument(document_id=LETTER, document_type="authorization_letter", name="Carta de autorización (carta.pdf)", parsed=parsed, **kw)


LETTER_DOC = _doc([(1, 0, "AUTORIZACIÓN DE DESCUENTO"), (2, 0, "Autorizo de manera irrevocable el descuento de S/ 350.00"), (3, 1, "Firma: ANA PEREZ DNI 12345678")])
PLAYBOOK = next(lens for lens in SEED_LENSES if lens.key == "legal_autorizacion_descuento")


def test_the_model_reads_numbered_lines_of_each_document() -> None:
    context, index, truncated = render_context([LETTER_DOC])
    assert "=== d1: Carta de autorización (carta.pdf) ===" in context
    assert "[d1:2] Autorizo de manera irrevocable el descuento de S/ 350.00" in context
    assert index["d1:3"].page == 1 and not truncated


def test_a_logical_document_inside_a_file_reads_only_its_pages() -> None:
    _, index, _ = render_context([_doc([(1, 0, "otro"), (2, 1, "mio"), (3, 2, "otro")], page_start=1, page_end=1)])
    assert list(index) == ["d1:2"]


def test_a_playbook_answer_keeps_its_evidence_and_flags_what_it_cannot_back() -> None:
    _, index, _ = render_context([LETTER_DOC])
    answer = PlaybookAnswer(
        headline="Cumple casi todo.",
        checks=[
            ClauseAnswer(item_key="irrevocable", status="cumple", explanation="Lo dice.", quote="autorizo de manera IRREVOCABLE", refs=["[d1:2]"]),
            ClauseAnswer(item_key="monto", status="cumple", explanation="S/ 350.", quote="descuento de S/ 500.00", refs=["d1:2"]),
            ClauseAnswer(item_key="firma_titular", status="cumple", explanation="Firmada.", quote="ANA PEREZ DNI 12345678", refs=["d1:3", "d9:99"]),
        ],
    )
    output = build_output(PLAYBOOK, answer, index, truncated=False)
    checks = {c.item_key: c for c in output.checks}
    assert checks["irrevocable"].quote_verified and checks["irrevocable"].evidence[0].page == 0
    assert checks["monto"].quote_verified is False, "S/ 500.00 is not what the letter says"
    assert output.unknown_refs == 1, "d9:99 does not exist: dropped, not shown"
    assert checks["beneficiario"].status == "dudoso" and "no se pronunció" in checks["beneficiario"].explanation
    assert [c.item_key for c in output.checks] == [i.key for i in PLAYBOOK.playbook], "every point, in the playbook's order"


def test_a_summary_cites_its_points() -> None:
    _, index, _ = render_context([LETTER_DOC])
    answer = LensSummaryAnswer(headline="Descuento de S/ 350.", points=[CitedPoint(text="Cuota S/ 350.", refs=["d1:2"])], attention=[CitedPoint(text="Falta el plazo.")])
    output = build_output(SEED_LENSES[0], answer, index, truncated=True)
    assert output.points[0].evidence[0].text.startswith("Autorizo") and output.attention[0].evidence == [] and output.truncated


def test_a_lens_definition_is_checked() -> None:
    with pytest.raises(ValueError, match="al menos un punto"):
        LensDefinition(key="x", name="X", area="legal", description="", kind="playbook")
    with pytest.raises(ValueError, match="única"):
        LensDefinition(key="x", name="X", area="legal", description="", kind="playbook", playbook=[PLAYBOOK.playbook[0], PLAYBOOK.playbook[0]])


def test_space_left_by_short_documents_goes_to_long_ones() -> None:
    from idp.domain.lenses import _budgets

    assert _budgets([100, 5000, 20000], 12000) == [100, 5000, 6900]
    assert sum(_budgets([3000, 2000, 7800, 5200], 24000)) == 18000, "everything fits: nothing is cut"


def test_the_extracted_data_comes_first_with_its_evidence() -> None:
    from idp.domain.lenses import render_facts
    from idp.domain.semantic_resolution import ConsolidatedView, EvidenceSource, ResolvedAttribute
    from idp.domain.semantic_seed import seed_catalog

    payslip = uuid.uuid4()
    view = ConsolidatedView(attributes=[
        ResolvedAttribute(role="titular", attribute="ingreso.neto_mensual", value=4304.14, status="single_source", distinct_values=[4304.14],
                          sources=[EvidenceSource(document_id=payslip, document_type="payslip", field_path="net_pay", value=4304.14, page=0, bbox=[0.5, 0.5, 0.6, 0.6])]),
    ])
    facts, index = render_facts(view, seed_catalog(), {payslip: "Boleta de pago (boleta.png)"})
    assert "[f1] Titular · Ingreso neto mensual: 4304.14 (Boleta de pago (boleta.png))" in facts
    context, full_index, _ = render_context([LETTER_DOC], facts, index)
    assert context.startswith("=== Datos ya extraídos del expediente ===")
    assert full_index["f1"].document_id == payslip and full_index["f1"].bbox == [0.5, 0.5, 0.6, 0.6]


def test_references_written_as_ranges_or_inside_the_text_still_cite() -> None:
    _, index, _ = render_context([LETTER_DOC])
    answer = LensSummaryAnswer(headline="h", points=[CitedPoint(text="Cuota irrevocable (d1:1-2).", refs=[]), CitedPoint(text="Firma [d1:3]", refs=["d1:3"])])
    output = build_output(SEED_LENSES[0], answer, index, truncated=False)
    assert output.points[0].text == "Cuota irrevocable." and [e.ref for e in output.points[0].evidence] == ["d1:1", "d1:2"]
    assert output.points[1].text == "Firma" and [e.ref for e in output.points[1].evidence] == ["d1:3"]
    assert output.unknown_refs == 0
