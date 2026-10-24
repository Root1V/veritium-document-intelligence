"""What of a document search indexes (VRT-59): its values as "field: value"
lines, and windows of each page's text that overlap and say their page."""

from __future__ import annotations

from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.search.chunks import OVERLAP_CHARS, WINDOW_CHARS, document_chunks, text_chunks, values_chunk


def _block(page: int, text: str, block_type: str = "text") -> ParsedBlock:
    return ParsedBlock(region_id=page * 100 + len(text), text=text, page=page, bbox=[0, 0, 1, 1], confidence=0.9, block_type=block_type)


def test_values_are_one_line_each_from_extracted_lists_and_plain_fields():
    payload = {
        "employee_name": {"value": "ANA QUISPE", "confidence": 0.9, "page": 0},
        "net_pay": {"value": 2345.5, "confidence": 0.8},
        "concepts": [{"name": {"value": "Sueldo", "confidence": 1}}, {"name": {"value": "Bono", "confidence": 1}}],
        "currency": "PEN",
        "notes": {"value": None, "confidence": 0.1},
        "empty": "",
    }
    chunk = values_chunk(payload)
    assert chunk is not None and chunk.kind == "valores" and chunk.page is None
    assert chunk.content.splitlines() == ["employee name: ANA QUISPE", "net pay: 2345.5", "concepts name: Sueldo", "concepts name: Bono", "currency: PEN"]
    assert values_chunk({}) is None and values_chunk(None) is None


def test_long_page_text_is_windowed_with_overlap_and_its_page():
    words = " ".join(f"palabra{i:04d}" for i in range(400))  # ~4800 chars
    chunks = text_chunks(ParsedDocument(backend="t", page_count=2, blocks=[_block(1, words)]))
    assert len(chunks) > 3 and {c.page for c in chunks} == {1}
    assert all(len(c.content) <= WINDOW_CHARS for c in chunks)
    first, second = chunks[0].content, chunks[1].content
    assert first.split()[-1] in second, "a phrase cut by a boundary is in the next window too"
    assert len(set(first.split()) & set(second.split())) * 12 >= OVERLAP_CHARS // 2
    assert " ".join(dict.fromkeys(w for c in chunks for w in c.content.split())) == words, "nothing is lost"


def test_a_segment_indexes_only_its_pages_and_figures_are_not_text():
    parsed = ParsedDocument(backend="t", page_count=3, blocks=[_block(0, "correo"), _block(1, "cronograma"), _block(1, "logo", "figure"), _block(2, "contrato")])
    pieces = document_chunks({"amount": {"value": 10, "confidence": 1}}, parsed, pages=(1, 2))
    assert [(c.kind, c.page, c.content) for c in pieces] == [("valores", None, "amount: 10"), ("texto", 1, "cronograma"), ("texto", 2, "contrato")]
    assert pieces[1].content_hash != pieces[2].content_hash and len(pieces[1].content_hash) == 64
