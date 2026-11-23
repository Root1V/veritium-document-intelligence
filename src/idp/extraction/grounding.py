"""Deterministic grounding post-processing for the agentic extraction loop.

The model reliably navigates to the *correct* region (its tool calls prove
that — see the ``reasoning_trace``) and reliably copies the region's *text*
into ``source_text``, but does not reliably carry the region's *page number*
through a long multi-turn conversation into the final ``submit_extraction``
call. Confirmed in practice on a 3-page BBVA loan form: a field whose
``source_text`` came verbatim from a page-2 region was submitted with
``page=0``.

Rather than keep tuning the prompt and hoping the model gets a mechanically
computable fact right every time, recompute ``page``/``bbox`` for every
``Extracted[T]`` leaf by matching it back against the parsed document's own
blocks — the same 'deterministic core, agentic reasoning shell' split used
elsewhere (arithmetic checks, DNI format): the LLM's job is deciding *what*
the value is; grounding it to a page/bbox is a lookup, not a judgment call,
and should never depend on the model narrating it correctly.

Two lookup strategies, tried in order:
1. **By region_id** (exact, preferred): if the model reported which
   region_id backed this field (``Extracted.region_id``) and that id
   resolves to a real block whose text is at least plausibly related to
   ``source_text``, use that block's page/bbox directly — no ambiguity.
   This is what resolves the case pure text-matching cannot: the *same*
   value legitimately printed on two different pages (e.g. a loan amount
   repeated as both 'requested' on page 1 and 'approved' on page 3) — only
   the region_id disambiguates which occurrence backed *this* field.
2. **By source_text** (fallback, best-effort): text-overlap search across
   all blocks, used when no region_id was reported, it doesn't resolve, or
   it points somewhere implausible (guards against a hallucinated id).
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

from idp.domain.envelope import Extracted, Unreadable
from idp.parsing.normalize import ParsedBlock, ParsedDocument


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def find_source_block(source_text: str, parsed: ParsedDocument) -> ParsedBlock | None:
    """Best-effort match: the block whose OCR text has the longest overlap
    with the field's source_text, in either containment direction (a
    multi-region read can produce a source_text that's a substring of one
    block, or a block whose text is a substring of a longer source_text)."""
    normalized_source = _normalize(source_text)
    if not normalized_source:
        return None

    best: ParsedBlock | None = None
    best_overlap = 0
    for block in parsed.blocks:
        normalized_block = _normalize(block.text)
        if not normalized_block:
            continue
        if normalized_block in normalized_source or normalized_source in normalized_block:
            overlap = min(len(normalized_block), len(normalized_source))
            if overlap > best_overlap:
                best = block
                best_overlap = overlap
    return best


def _plausible_match(region_text: str, source_text: str) -> bool:
    """Sanity check before trusting a model-reported region_id: the block's
    own text should have *some* overlap with source_text — guards against a
    hallucinated/stale region_id silently grounding a field to the wrong
    place instead of falling back to the text-search strategy."""
    normalized_region = _normalize(region_text)
    normalized_source = _normalize(source_text)
    if not normalized_region or not normalized_source:
        return False
    return normalized_region in normalized_source or normalized_source in normalized_region


def _resolve_by_region_id(field: Extracted, parsed: ParsedDocument) -> ParsedBlock | None:
    if field.region_id is None:
        return None
    block = parsed.block(field.region_id)
    if block is None:
        return None
    if not _plausible_match(block.text, field.source_text or ""):
        return None
    return block


def attach_grounding(instance: BaseModel, parsed: ParsedDocument) -> None:
    """Recursively overwrites page/bbox on every Extracted[T] leaf, using
    the parsed document as ground truth — by region_id when the model
    reported one and it checks out, else by source_text search."""
    _attach_recursive(instance, parsed)


def _attach_recursive(value: object, parsed: ParsedDocument) -> None:
    if isinstance(value, Unreadable):  # VRT-112: the page to ask for again
        block = parsed.block(value.region_id) if value.region_id is not None else None
        value.page = block.page if block is not None else None
    elif isinstance(value, Extracted):
        block = _resolve_by_region_id(value, parsed) or find_source_block(value.source_text or "", parsed)
        if block is not None:
            value.page = block.page
            value.bbox = block.bbox
            value.read_confidence = block.confidence
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            _attach_recursive(getattr(value, name), parsed)
    elif isinstance(value, list):
        for item in value:
            _attach_recursive(item, parsed)
