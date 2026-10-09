"""Automates the judgment call this platform's operators have made by hand
for every ``DocumentType`` added so far: when a document falls into
``generic``, decide whether its content looks like a stable, recurring
business document type worth promoting, and if so draft a concrete
proposal (name + fields + rationale). A human still decides whether to
accept it — see ``api/routes/type_suggestions.py`` — this module only
drafts the proposal; the platform never registers a new ``DocumentType``
on its own.

Different companies/institutions attaching a document to a loan file can
each use their own template for what is conceptually the same document
type. That drift is exactly what the bounded agentic extraction loop
already tolerates *within* a known type (see ``extraction/agentic/``
docstrings) — this module is the analogous tolerance one level up, for
document *types* the platform has never seen at all, rather than layout
variance within a known one.
"""

from __future__ import annotations

from idp.config import Settings
from idp.domain.document_type_catalog import DocumentTypeCatalog
from idp.domain.schemas.generic import GenericSchema
from idp.domain.type_suggestion import DocumentTypeProposal
from idp.llm.port import structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call

_SYSTEM_PROMPT = prompt("suggest_document_type", """Eres un agente que decide si un documento sin clasificar deberia convertirse en un \
tipo de documento propio de la plataforma, en vez de seguir cayendo en el extractor generico.

Tipos ya conocidos por la plataforma (NO propongas un tipo redundante con alguno de estos):
{known_types}

Se te da el resultado de una extraccion generica (campos clave-valor + resumen) de UN documento. \
Decide:

1. is_promotable: True SOLO si el contenido tiene una forma de negocio estable y repetible — es \
decir, si empresas/instituciones distintas probablemente envien este mismo tipo de documento con un \
conjunto de campos similar (aunque el layout fisico varie). False si el documento es demasiado unico, \
ruidoso, o parece un caso aislado que no vale la pena estandarizar.

2. Si is_promotable es True: propon un nombre de tipo en snake_case ingles (siguiendo la convencion de \
los tipos ya conocidos arriba), un nombre legible en español, una justificacion breve de por que \
amerita un tipo propio y en que se distingue de los tipos ya conocidos, y una lista de campos \
propuestos (nombre en snake_case ingles, tipo, descripcion EXPLICITA en español de que representa y \
de donde se extrae, y si es consistentemente requerido u opcional).

3. Si is_promotable es False: deja rationale explicando por que, y fields vacio.""", filled=('known_types',))


def suggest_document_type(settings: Settings, generic_result: GenericSchema, catalog: DocumentTypeCatalog) -> DocumentTypeProposal:
    known_types = "\n".join(f"- {k}: {catalog.current(k)[1].description}" for k in catalog.keys())  # type: ignore[index]
    fields_summary = "\n".join(f"- {f.key}: {f.value.value!r}" for f in generic_result.fields)
    summary = generic_result.summary.value if generic_result.summary else ""
    with traced_llm_call(role="reasoning", model=settings.reasoning_model):
        return structured(
            purpose="suggest_document_type",
            role="reasoning",
            output=DocumentTypeProposal,
            instructions=_SYSTEM_PROMPT.render(known_types=known_types),
            task=f"Resumen: {summary}\n\nCampos extraidos:\n{fields_summary}",
        )
