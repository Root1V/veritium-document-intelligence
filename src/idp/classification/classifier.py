"""Document-type classification — new relative to the PoC, which had no
notion of document-level type (only PaddleOCR's built-in per-*region* labels).
A single structured-output call produces a routing decision; nothing
downstream needs to know how that decision was made."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, create_model

from idp.config import Settings
from idp.domain.document_type_catalog import GENERIC, DocumentTypeCatalog
from idp.llm.port import structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument

GENERIC_DESCRIPTION = "cualquier otro documento que no encaje claramente en los tipos anteriores"

_SYSTEM_PROMPT = prompt("classify", """Eres un clasificador de documentos empresariales. Dado el texto \
extraido de un documento, determina su tipo. Los tipos validos son:
{types}

Si el documento no encaja claramente en ninguno de los tipos especificos, clasifica como generic.
Responde con el tipo, tu confianza (0-1) y una breve justificacion.""")


class ClassificationResult(BaseModel):
    document_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


@lru_cache(maxsize=32)
def _result_model(keys: tuple[str, ...]) -> type[ClassificationResult]:
    """The answer can only name a published type or generic: the enum
    travels in the structured-output schema, so anything else is re-asked."""
    return create_model("ClassificationResult", __base__=ClassificationResult, document_type=(Literal[(*keys, GENERIC)], ...))


def classify(settings: Settings, parsed: ParsedDocument, catalog: DocumentTypeCatalog) -> ClassificationResult:
    """The types offered are the catalog's published ones (VRT-32), read per
    call — a type published a minute ago is classifiable now."""
    keys = catalog.keys()
    types = "\n".join(
        [f"- {k}: {catalog.current(k)[1].description}" for k in keys] + [f"- {GENERIC}: {GENERIC_DESCRIPTION}"]  # type: ignore[index]
    )
    text_excerpt = parsed.full_text[:4000]
    with traced_llm_call(role="reasoning", model=settings.reasoning_model):
        result = structured(
            purpose="classify",
            role="reasoning",
            output=_result_model(tuple(keys)),
            instructions=_SYSTEM_PROMPT.render(types=types),
            task=f"Texto del documento:\n\n{text_excerpt}",
        )
    return result


def needs_review(settings: Settings, result: ClassificationResult) -> bool:
    return result.confidence < settings.classification_confidence_threshold or result.document_type == GENERIC
