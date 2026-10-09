"""Thin, synchronous stage functions — the seam designed for a mechanical
promotion to Prefect/Temporal in Fase 1+: each stage is ``(input, context)
-> output``, OTEL-traced, with no knowledge of persistence or orchestration.
Kept synchronous (LLM/OCR calls are blocking) and run via
``asyncio.to_thread`` from the async orchestrator."""

from __future__ import annotations

from idp.classification.classifier import ClassificationResult, classify
from idp.classification.type_discovery import suggest_document_type
from idp.config import Settings
from idp.domain.document_type_catalog import GENERIC, DocumentTypeCatalog
from idp.domain.schemas.generic import GenericSchema
from idp.domain.type_suggestion import DocumentTypeProposal
from idp.extraction.base import ExtractionOutcome
from idp.extraction.catalog_extractor import extract_catalog_type
from idp.extraction.generic import GenericExtractor
from idp.observability.otel import traced_stage
from idp.parsing.base import ParserBackend
from idp.parsing.normalize import ParsedDocument
from idp.segmentation.splitter import DocumentSegment, detect_segments


def parse_document(settings: Settings, backend: ParserBackend, file_bytes: bytes, filename: str, *, document_id: str) -> ParsedDocument:
    with traced_stage("parse", document_id=document_id, backend=backend.name):
        return backend.parse(file_bytes, filename)


def segment_document(settings: Settings, parsed: ParsedDocument, *, document_id: str) -> list[DocumentSegment]:
    with traced_stage("segment", document_id=document_id, page_count=parsed.page_count):
        return detect_segments(settings, parsed)


def classify_document(settings: Settings, parsed: ParsedDocument, catalog: DocumentTypeCatalog, *, document_id: str) -> ClassificationResult:
    with traced_stage("classify", document_id=document_id):
        return classify(settings, parsed, catalog)


def extract_document(
    settings: Settings,
    parsed: ParsedDocument,
    document_type: str,
    catalog: DocumentTypeCatalog,
    *,
    document_id: str,
    correction_note: str | None = None,
    grounding: dict[str, str] | None = None,
) -> ExtractionOutcome:
    with traced_stage("extract", document_id=document_id, document_type=document_type):
        if document_type == GENERIC:
            return GenericExtractor().extract(parsed, settings, correction_note)
        return extract_catalog_type(parsed, settings, catalog, document_type, correction_note, grounding=grounding)


def suggest_type(settings: Settings, generic_result: GenericSchema, catalog: DocumentTypeCatalog, *, document_id: str) -> DocumentTypeProposal:
    with traced_stage("suggest_type", document_id=document_id):
        return suggest_document_type(settings, generic_result, catalog)
