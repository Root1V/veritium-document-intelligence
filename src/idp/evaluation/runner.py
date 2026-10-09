"""Runs an evaluation suite (VRT-42): each case is parsed, classified and
extracted with the configuration of the moment — the same stages a case
run uses, without creating a case, a review item or an event — and
compared with what it should produce. Cases run in parallel up to
``case_max_parallel_documents``; each result is written as soon as it
exists, so an interrupted run resumes with the cases left.

It runs in the API process, like the interim case executor: not durable,
but resumable (POST the run again). Gateway responses to an identical
request within its idempotency window are replays, so re-running an
unchanged suite costs nothing; any change to a model, prompt or type
changes the request and is measured fresh."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from idp.config import Settings
from idp.domain.document_type_catalog import DocumentTypeCatalog
from idp.domain.evaluation import CaseOutcome, FieldResult, compare_fields, summarize
from idp.extraction.agentic.loop import ExtractionIncomplete
from idp.parsing.normalize import slice_by_pages
from idp.persistence.db import get_session_factory
from idp.persistence.models import EvalCase, EvalResult
from idp.persistence.repositories import DocumentTypeRepository, EvaluationRepository
from idp.pipeline.orchestrator import extraction_grounding, parse_example
from idp.pipeline.provenance import build_provenance
from idp.pipeline.stages import classify_document, extract_document
from idp.storage.object_store import S3ObjectStore

# Runs executing in this process: starting one twice would only duplicate work.
_active: set[uuid.UUID] = set()


def is_active(run_id: uuid.UUID) -> bool:
    return run_id in _active


def outcome_of(result: EvalResult, case: EvalCase) -> CaseOutcome:
    return CaseOutcome(
        case_id=str(case.id),
        expected_document_type=case.expected_document_type,
        predicted_document_type=result.predicted_document_type,
        failed=result.status == "failed",
        fields=[FieldResult.model_validate(f) for f in result.field_results],
    )


async def _evaluate(settings: Settings, case: EvalCase, run_id: uuid.UUID, catalog: DocumentTypeCatalog, grounding: bool) -> EvalResult:
    started = time.monotonic()
    label = f"eval-{case.id}"
    predicted: str | None = None
    confidence: float | None = None
    try:
        file_bytes = await asyncio.to_thread(S3ObjectStore(settings).get, case.storage_key)
        parsed = await asyncio.to_thread(parse_example, settings, file_bytes, case.filename)
        if case.page_start is not None:
            parsed = slice_by_pages(parsed, case.page_start, case.page_end if case.page_end is not None else case.page_start)
        classification = await asyncio.to_thread(classify_document, settings, parsed, catalog, document_id=label)
        predicted, confidence = classification.document_type, classification.confidence
        async with get_session_factory(settings)() as session:
            meanings = await extraction_grounding(settings, session, predicted, enabled=grounding)
        try:
            outcome = await asyncio.to_thread(extract_document, settings, parsed, predicted, catalog, document_id=label, grounding=meanings)
            payload: dict[str, Any] | None = outcome.schema_instance.model_dump(mode="json") if outcome.schema_instance is not None else None
        except ExtractionIncomplete:
            payload = None  # measured as every expected field missing
        current = catalog.current(case.expected_document_type or predicted)
        fields = compare_fields(current[1].fields if current else [], case.expected_fields, payload)
        status, error = "done", None
    except Exception as exc:
        fields, status, error = [], "failed", f"{type(exc).__name__}: {exc}"[:2000]
    return EvalResult(
        run_id=run_id,
        case_id=case.id,
        status=status,
        predicted_document_type=predicted,
        classification_confidence=confidence,
        field_results=[f.model_dump(mode="json") for f in fields],
        error=error,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


async def run_evaluation(settings: Settings, run_id: uuid.UUID) -> None:
    if run_id in _active:
        return
    _active.add(run_id)
    factory = get_session_factory(settings)
    try:
        async with factory() as session:
            repo = EvaluationRepository(session)
            run = await repo.get_run(run_id)
            if run is None or run.status == "completed":
                return
            catalog = await DocumentTypeRepository(session).load_catalog()
            if run.status == "pending":
                provenance = build_provenance(settings, profile_version=None, rules=[])
                for key in ("profile", "semantic_catalog_version", "thresholds", "rules"):
                    provenance.pop(key, None)
                provenance["document_types"] = {key: current[0] for key in catalog.keys() if (current := catalog.current(key)) is not None}
                provenance["semantic_grounding"] = (run.options or {}).get("semantic_grounding", settings.extraction_semantic_grounding)
                run.status, run.started_at, run.provenance = "running", datetime.now(UTC), provenance
                await session.commit()
            grounding = bool((run.provenance or {}).get("semantic_grounding"))
            done = {r.case_id for r in run.results}
            pending = [c for c in run.suite.cases if c.id not in done]

        semaphore = asyncio.Semaphore(settings.case_max_parallel_documents)

        async def one(case: EvalCase) -> None:
            async with semaphore:
                result = await _evaluate(settings, case, run_id, catalog, grounding)
            async with factory() as session:
                await EvaluationRepository(session).save_result(result)
                await session.commit()

        await asyncio.gather(*(one(c) for c in pending))

        async with factory() as session:
            run = await EvaluationRepository(session).get_run(run_id)
            assert run is not None
            cases = {c.id: c for c in run.suite.cases}
            run.metrics = summarize([outcome_of(r, cases[r.case_id]) for r in run.results])
            run.status, run.finished_at = "completed", datetime.now(UTC)
            await session.commit()
    except Exception as exc:
        async with factory() as session:
            run = await EvaluationRepository(session).get_run(run_id)
            if run is not None:
                run.status, run.error, run.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:2000], datetime.now(UTC)
                await session.commit()
        raise
    finally:
        _active.discard(run_id)
