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
from idp.llm.port import structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument


class DocumentSegment(BaseModel):
    start_page: int = Field(description="Primera pagina (0-indexed) de este documento logico.")
    end_page: int = Field(description="Ultima pagina (0-indexed, inclusive) de este documento logico.")
    reasoning: str = Field(description="Por que estas paginas forman un documento logico distinto de las demas.")


class _SegmentationResult(BaseModel):
    segments: list[DocumentSegment]


_SYSTEM_PROMPT = prompt("segment", """Eres un agente que detecta los limites entre documentos logicos distintos dentro \
de un unico archivo PDF fisico subido por un cliente. Un archivo fisico puede contener MAS DE UN \
documento logico concatenado — p. ej. un correo electronico de portada, seguido de un cronograma de \
pagos, seguido de terminos y condiciones contractuales, seguido de un estado de cuenta: cada uno un \
documento funcional distinto para la empresa, aunque vengan juntos en el mismo PDF.

SESGO POR DEFECTO: ante la duda, NO separes. Dividir de mas rompe un documento que debia leerse como \
un todo (p. ej. una solicitud con secciones A, B, C... M, donde la seccion de firmas o de fiador en \
una pagina posterior pertenece al mismo formulario que las secciones anteriores, aunque el tema de \
esa pagina — firmas, garantias, un aviso legal — parezca distinto a primera vista). Senales que NO \
justifican por si solas una separacion: cambio de tema/seccion dentro de un mismo formulario, \
encabezado o pie de pagina repetido, numeracion de pagina, o texto en blanco al final de una pagina.

Senales que SI justifican una separacion en documentos logicos distintos: cambio de institucion o \
remitente (p. ej. un correo interno de un banco seguido de un documento emitido por una entidad \
financiera distinta), un titulo de documento completamente diferente (p. ej. pasa de un formulario de \
solicitud a un cronograma de pagos, o de un cronograma a un estado de cuenta), o un tipo de contenido \
fundamentalmente distinto (correo electronico vs formulario vs tabla vs estado de cuenta).

Un documento logico puede abarcar VARIAS paginas si su contenido continua naturalmente de una pagina \
a la siguiente (p. ej. un formulario de varias paginas con secciones marcadas A, B, C..., o una tabla \
larga) — NO separes paginas que son continuacion del mismo documento solo porque cambian de seccion o \
de tema.

Se te da un resumen del texto de cada pagina. Identifica los rangos [start_page, end_page] (0-indexed, \
inclusive) de cada documento logico distinto, en orden de aparicion. Los rangos deben cubrir el \
documento completo, sin huecos ni superposiciones. Si tienes dudas sobre si dos paginas son el mismo \
documento, trata ambas como parte de UN solo segmento.""")


def _page_excerpts(parsed: ParsedDocument, max_chars_per_page: int = 6000) -> str:
    lines = []
    for page in range(parsed.page_count):
        page_text = " | ".join(b.text for b in parsed.blocks if b.page == page and b.text.strip())
        lines.append(f"--- Pagina {page} ---\n{page_text[:max_chars_per_page]}")
    return "\n\n".join(lines)


def detect_segments(settings: Settings, parsed: ParsedDocument) -> list[DocumentSegment]:
    if parsed.page_count <= 1:
        return [DocumentSegment(start_page=0, end_page=0, reasoning="Documento de una sola pagina.")]

    with traced_llm_call(role="reasoning", model=settings.reasoning_model):
        result = structured(
            purpose="segment",
            role="reasoning",
            output=_SegmentationResult,
            instructions=_SYSTEM_PROMPT.render(),
            task=_page_excerpts(parsed),
        )
    return result.segments or [DocumentSegment(start_page=0, end_page=parsed.page_count - 1, reasoning="Fallback: sin segmentos detectados.")]
