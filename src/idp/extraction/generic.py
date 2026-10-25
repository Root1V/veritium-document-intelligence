"""Fallback extractor for unclassified/low-confidence documents. Deliberately
does NOT use the bounded agentic loop: there is no fixed field set to look
for (that's precisely what makes a document 'generic'), so a multi-turn
region-inspection loop buys nothing here — a single best-effort structured
call is enough."""

from __future__ import annotations

from idp.config import Settings
from idp.domain.schemas.generic import GenericSchema
from idp.extraction.base import ExtractionOutcome, attach_trace
from idp.extraction.grounding import attach_grounding
from idp.llm.port import model_for, structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument

_SYSTEM_PROMPT = prompt("extract_generic", """You are a data extraction assistant. The document could not be classified into a known type. \
Extract the most relevant key-value pairs you find (names, amounts, dates, identifiers) and a brief summary. Each \
field must include its confidence level (0-1) and the exact source text.

Each field's key is read by a person, not a program: write it in Spanish, as that data would be named in the \
document (e.g. "Monto solicitado", "DNI del cónyuge", "Fecha de emisión"). Never in English or snake_case. If the \
document carries data of several people, tell them apart by their role or by order ("DNI del titular", \
"Nombres — persona 2"), never by their name: the key must not contain anyone's data. The summary is also in \
Spanish. Copy values exactly as the document writes them; never translate them.""")


class GenericExtractor:
    def extract(self, parsed: ParsedDocument, settings: Settings, correction_note: str | None = None) -> ExtractionOutcome:
        text = parsed.full_text[:6000]
        with traced_llm_call(role="reasoning", model=model_for("reasoning")):
            result = structured(
                purpose="extract_generic",
                role="reasoning",
                output=GenericSchema,
                instructions=_SYSTEM_PROMPT.render(),
                task=f"Document text:\n\n{text}",
            )
        attach_trace(result, [])  # no-op: generic extraction never uses tool calls
        attach_grounding(result, parsed)
        return ExtractionOutcome(schema_instance=result, needs_review=True, review_reason="unclassified_document", extraction_method="fixed")
