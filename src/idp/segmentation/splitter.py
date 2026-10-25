"""Detects whether a single physical upload actually bundles more than one
logical document — a real case found in practice (2026-08-23:
'302_Cronograma subrogado-Estado de cuenta', a 7-page PDF that turned out to
contain an email cover, a payment schedule, contract terms-and-conditions,
and an account statement concatenated into one file). Forcing the whole
bundle through a single classify->extract pass against one target schema is
what caused that document to time out.

Where a logical document's boundary falls is a judgment call — the same
'agentic reasoning shell' principle used for classification — so this is an
LLM call, not a page-count/blank-page heuristic. A logical document can span
multiple pages when content clearly continues (a multi-page form, a long
table); the prompt is told not to split those apart.

Single-page uploads skip the LLM call: one page cannot bundle more than one
logical document under this platform's page-range segmentation model, so the
fast path returns a single whole-file segment at zero cost — every
previously-working single/multi-page-but-single-document case (e.g. the
3-page loan_application form) is unaffected.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from idp.config import Settings
from idp.llm.port import model_for, structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument


class DocumentSegment(BaseModel):
    start_page: int = Field(description="First page (0-indexed) of this logical document.")
    end_page: int = Field(description="Last page (0-indexed, inclusive) of this logical document.")
    reasoning: str = Field(description="In Spanish: why these pages form a logical document distinct from the others.")


class _SegmentationResult(BaseModel):
    segments: list[DocumentSegment]


_SYSTEM_PROMPT = prompt("segment", """You are an agent that detects the boundaries between distinct logical documents inside a single \
physical PDF file uploaded by a client. A physical file can contain MORE THAN ONE concatenated logical document — \
e.g. a cover email, followed by a payment schedule, followed by contractual terms and conditions, followed by an \
account statement: each one a functionally distinct document for the business, even though they come together in \
the same PDF.

DEFAULT BIAS: when in doubt, do NOT split. Over-splitting breaks a document that had to be read as a whole (e.g. an \
application with sections A, B, C... M, where the signatures or guarantor section on a later page belongs to the \
same form as the earlier sections, even if the topic of that page — signatures, guarantees, a legal notice — looks \
different at first sight). Signals that do NOT justify a split by themselves: a change of topic/section within the \
same form, a repeated header or footer, page numbering, or blank text at the end of a page.

Signals that DO justify a split into distinct logical documents: a change of institution or sender (e.g. an \
internal email of a bank followed by a document issued by a different financial institution), a completely \
different document title (e.g. it goes from an application form to a payment schedule, or from a schedule to an \
account statement), or a fundamentally different kind of content (email vs form vs table vs account statement).

A logical document can span SEVERAL pages if its content naturally continues from one page to the next (e.g. a \
multi-page form with sections marked A, B, C..., or a long table) — do NOT split pages that continue the same \
document just because they change section or topic.

You are given an excerpt of the text of each page (the documents are in Spanish). Identify the ranges \
[start_page, end_page] (0-indexed, inclusive) of each distinct logical document, in order of appearance. The ranges \
must cover the whole document, without gaps or overlaps. If you are unsure whether two pages are the same document, \
treat both as part of ONE single segment. Write each reasoning in Spanish.""")


def _page_excerpts(parsed: ParsedDocument, max_chars_per_page: int = 6000) -> str:
    lines = []
    for page in range(parsed.page_count):
        page_text = " | ".join(b.text for b in parsed.blocks if b.page == page and b.text.strip())
        lines.append(f"--- Page {page} ---\n{page_text[:max_chars_per_page]}")
    return "\n\n".join(lines)


def detect_segments(settings: Settings, parsed: ParsedDocument) -> list[DocumentSegment]:
    if parsed.page_count <= 1:
        return [DocumentSegment(start_page=0, end_page=0, reasoning="Documento de una sola pagina.")]

    with traced_llm_call(role="reasoning", model=model_for("reasoning")):
        result = structured(
            purpose="segment",
            role="reasoning",
            output=_SegmentationResult,
            instructions=_SYSTEM_PROMPT.render(),
            task=_page_excerpts(parsed),
        )
    return result.segments or [DocumentSegment(start_page=0, end_page=parsed.page_count - 1, reasoning="Fallback: sin segmentos detectados.")]
