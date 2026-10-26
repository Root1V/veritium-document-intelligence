"""Back pages tied to their record by the machine-readable line (VRT-103):
two ID cards whose backs come in reverse order are paired by number, not by page."""

from __future__ import annotations

from idp.extraction.agentic.prompts import _linked_pages
from idp.parsing.normalize import ParsedBlock, ParsedDocument


def _block(region_id: int, page: int, text: str) -> ParsedBlock:
    return ParsedBlock(region_id=region_id, text=text, page=page, bbox=[0, 0, 1, 1], confidence=0.9)


def test_backs_in_reverse_order_are_tied_to_their_card_by_number():
    parsed = ParsedDocument(
        backend="test",
        page_count=4,
        blocks=[
            _block(1, 0, "N° 123456789"),
            _block(2, 1, "N° 987654321"),
            _block(3, 2, "P0000001"),
            _block(4, 2, "9876543215CHL7901058F2201199<<<<<<<2"),
            _block(5, 3, "C<CHLPEREZ<<ANA<<<<<<<<<<<<<"),
            _block(6, 3, "1234567894CHL7607280M2202277<<<<<<<6"),
        ],
    )
    said = _linked_pages(parsed)
    assert "- page 2 belongs to the record numbered 987654321 (printed on page 1)" in said
    assert "- page 3 belongs to the record numbered 123456789 (printed on page 0)" in said


def test_a_document_without_machine_readable_lines_adds_nothing():
    parsed = ParsedDocument(backend="test", page_count=1, blocks=[_block(1, 0, "Boleta N° 123456789"), _block(2, 0, "NETO 3 497,20")])
    assert _linked_pages(parsed) == ""
