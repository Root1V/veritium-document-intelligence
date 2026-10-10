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

_SYSTEM_PROMPT = prompt("extract_generic", """Eres un asistente de extraccion de datos. El documento no pudo clasificarse en un \
tipo conocido. Extrae los pares clave-valor mas relevantes que encuentres (nombres, montos, fechas, \
identificadores) y un resumen breve. Cada campo debe incluir su nivel de confianza (0-1) y el texto \
exacto de origen.""")


class GenericExtractor:
    def extract(self, parsed: ParsedDocument, settings: Settings, correction_note: str | None = None) -> ExtractionOutcome:
        text = parsed.full_text[:6000]
        with traced_llm_call(role="reasoning", model=model_for("reasoning")):
            result = structured(
                purpose="extract_generic",
                role="reasoning",
                output=GenericSchema,
                instructions=_SYSTEM_PROMPT.render(),
                task=f"Texto del documento:\n\n{text}",
            )
        attach_trace(result, [])  # no-op: generic extraction never uses tool calls
        attach_grounding(result, parsed)
        return ExtractionOutcome(schema_instance=result, needs_review=True, review_reason="unclassified_document", extraction_method="fixed")
