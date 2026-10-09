"""The extractor for every catalog type (VRT-32): the bounded agentic loop
over the type version's compiled schema and extraction hint. It replaces
one identical module per type — what differed between types was always
data (schema, field descriptions, hint), never code."""

from __future__ import annotations

from idp.config import Settings
from idp.domain.document_type_catalog import DocumentTypeCatalog
from idp.extraction.agentic.loop import ExtractionIncomplete, run_agentic_extraction
from idp.extraction.base import ExtractionOutcome, attach_trace
from idp.extraction.grounding import attach_grounding
from idp.parsing.normalize import ParsedDocument


def extract_catalog_type(
    parsed: ParsedDocument,
    settings: Settings,
    catalog: DocumentTypeCatalog,
    type_key: str,
    correction_note: str | None = None,
    *,
    grounding: dict[str, str] | None = None,
) -> ExtractionOutcome:
    current = catalog.current(type_key)
    if current is None:
        raise ValueError(f"tipo documental '{type_key}' sin versión publicada")
    version, definition = current
    schema_version = str(version)
    try:
        result, trace = run_agentic_extraction(
            settings,
            parsed,
            catalog.schema(type_key, version),  # type: ignore[arg-type]
            # The version is part of what is extracted: a new schema is a new
            # request, never a replay of the previous version's.
            purpose=f"extract/{type_key}/v{version}",
            hint=definition.extraction_hint,
            correction_note=correction_note,
            grounding=grounding,
        )
    except ExtractionIncomplete as exc:
        return ExtractionOutcome(schema_instance=None, needs_review=True, review_reason=str(exc), extraction_method="agentic", schema_version=schema_version)
    attach_trace(result, trace)
    attach_grounding(result, parsed)
    return ExtractionOutcome(schema_instance=result, needs_review=False, extraction_method="agentic", schema_version=schema_version)
