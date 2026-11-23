"""Deterministic grounding must correct page/bbox even when the model's
self-reported page is wrong — this is the fix for a real bug found in
practice: a field whose source_text came verbatim from a page-2 region was
submitted by the agent with page=0."""

from __future__ import annotations

from idp.domain.envelope import Extracted
from idp.extraction.grounding import attach_grounding
from idp.parsing.normalize import ParsedBlock, ParsedDocument


def _parsed_with_blocks() -> ParsedDocument:
    return ParsedDocument(
        backend="test",
        page_count=3,
        blocks=[
            ParsedBlock(region_id=0, text="PERIODO: ENERO - 2026", page=0, bbox=[0.1, 0.1, 0.3, 0.12], confidence=0.9),
            ParsedBlock(region_id=1, text="SOLICITUD APROBADA:", page=2, bbox=[0.2, 0.5, 0.5, 0.52], confidence=0.9),
            ParsedBlock(region_id=2, text="Xsi", page=2, bbox=[0.5, 0.5, 0.55, 0.52], confidence=0.9),
            # Same value legitimately printed on two different pages — this
            # is the case pure text-matching cannot resolve on its own.
            ParsedBlock(region_id=3, text="132500.00", page=0, bbox=[0.3, 0.2, 0.4, 0.22], confidence=0.9),
            ParsedBlock(region_id=4, text="132500.00", page=2, bbox=[0.3, 0.6, 0.4, 0.62], confidence=0.9),
        ],
    )


def test_attach_grounding_overrides_wrong_self_reported_page():
    # The model claims page=0 (wrong) for a value whose source_text matches
    # a block that is genuinely on page 2.
    field = Extracted(value="SI", page=0, bbox=None, confidence=1.0, source_text="Xsi")
    parsed = _parsed_with_blocks()
    attach_grounding(field, parsed)
    assert field.page == 2
    assert field.bbox == [0.5, 0.5, 0.55, 0.52]


def test_attach_grounding_matches_on_normalized_text():
    field = Extracted(value="ENERO - 2026", page=99, bbox=None, confidence=1.0, source_text="periodo:   enero - 2026")
    parsed = _parsed_with_blocks()
    attach_grounding(field, parsed)
    assert field.page == 0


def test_attach_grounding_leaves_field_unchanged_when_no_match():
    field = Extracted(value="unrelated", page=5, bbox=[0.9, 0.9, 0.95, 0.95], confidence=1.0, source_text="nothing like any block")
    parsed = _parsed_with_blocks()
    attach_grounding(field, parsed)
    assert field.page == 5
    assert field.bbox == [0.9, 0.9, 0.95, 0.95]


def test_attach_grounding_uses_region_id_to_disambiguate_duplicate_text():
    # Both region 3 (page 0) and region 4 (page 2) have identical OCR text
    # ("132500.00") — pure source_text matching cannot tell them apart.
    # region_id resolves it exactly.
    field = Extracted(value=132500.0, page=0, bbox=None, confidence=1.0, source_text="132500.00", region_id=4)
    parsed = _parsed_with_blocks()
    attach_grounding(field, parsed)
    assert field.page == 2
    assert field.bbox == [0.3, 0.6, 0.4, 0.62]


def test_attach_grounding_falls_back_to_text_search_when_region_id_missing():
    field = Extracted(value=132500.0, page=99, bbox=None, confidence=1.0, source_text="132500.00", region_id=None)
    parsed = _parsed_with_blocks()
    attach_grounding(field, parsed)
    # No region_id given — falls back to text search, which (by construction
    # of find_source_block's "first best match" rule) lands on whichever
    # duplicate it encounters first. The key behavior under test is that a
    # region_id, when present, always wins over this fallback.
    assert field.page in (0, 2)


def test_attach_grounding_ignores_hallucinated_region_id():
    # region_id=0 points to a block ("PERIODO: ENERO - 2026") with no
    # relation to this field's source_text — must not trust it blindly.
    field = Extracted(value=132500.0, page=99, bbox=None, confidence=1.0, source_text="132500.00", region_id=0)
    parsed = _parsed_with_blocks()
    attach_grounding(field, parsed)
    assert field.page != 99  # still got grounded, just via the text-search fallback
    assert field.page in (0, 2)


def test_attach_grounding_walks_nested_models_and_lists():
    from pydantic import BaseModel

    class Item(BaseModel):
        name: Extracted[str]

    class Container(BaseModel):
        items: list[Item]

    container = Container(items=[Item(name=Extracted(value="x", page=0, bbox=None, confidence=1.0, source_text="Xsi"))])
    parsed = _parsed_with_blocks()
    attach_grounding(container, parsed)
    assert container.items[0].name.page == 2
