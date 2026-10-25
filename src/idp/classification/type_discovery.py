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
from idp.llm.port import model_for, structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call

_SYSTEM_PROMPT = prompt("suggest_document_type", """You are an agent that decides whether an unclassified document should become a document type of its \
own on the platform, instead of keep falling into the generic extractor.

Types already known to the platform (do NOT propose a type redundant with any of these):
{known_types}

You are given the result of a generic extraction (key-value fields + summary) of ONE document. Decide:

1. is_promotable: True ONLY if the content has a stable, repeatable business form — that is, if different \
companies/institutions would likely send this same kind of document with a similar set of fields (even if the \
physical layout varies). False if the document is too unique, noisy, or looks like an isolated case not worth \
standardizing.

2. If is_promotable is True: propose a type name in English snake_case (following the convention of the known \
types above), a readable name in Spanish, a brief justification in Spanish of why it deserves its own type and how \
it differs from the known types, and a list of proposed fields (name in English snake_case, type, an EXPLICIT \
description in Spanish of what it represents and where it is extracted from, and whether it is consistently \
required or optional).

3. If is_promotable is False: write the rationale in Spanish explaining why, and leave fields empty.""", filled=('known_types',))


def suggest_document_type(settings: Settings, generic_result: GenericSchema, catalog: DocumentTypeCatalog) -> DocumentTypeProposal:
    known_types = "\n".join(f"- {k}: {catalog.current(k)[1].description}" for k in catalog.keys())  # type: ignore[index]
    fields_summary = "\n".join(f"- {f.key}: {f.value.value!r}" for f in generic_result.fields)
    summary = generic_result.summary.value if generic_result.summary else ""
    with traced_llm_call(role="reasoning", model=model_for("reasoning")):
        return structured(
            purpose="suggest_document_type",
            role="reasoning",
            output=DocumentTypeProposal,
            instructions=_SYSTEM_PROMPT.render(known_types=known_types),
            task=f"Summary: {summary}\n\nExtracted fields:\n{fields_summary}",
        )
