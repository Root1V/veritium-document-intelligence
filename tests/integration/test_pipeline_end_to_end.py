"""End-to-end: parse -> classify -> extract -> validate against the real
PoC fixtures, run through the actual orchestrator (not the API layer — see
``test_api_upload_flow.py`` for that). Needs Postgres/MinIO up and a
reachable reasoning/vision LLM endpoint; skips cleanly otherwise.

Requires migrations applied first: ``uv run alembic upgrade head``.

The bounded agentic extraction loop is not guaranteed to converge on every
single run against a small local reasoning model (this is exactly why
non-convergence routes to ``needs_review`` instead of crashing — see
``extraction/agentic/loop.py``). A couple of retries here absorbs that
variance while still failing loudly on an actual regression (e.g. a
consistent 0-for-N run, or wrong values on a converged run).
"""

from __future__ import annotations

import json

import pytest

from idp.persistence.db import get_session_factory
from idp.persistence.repositories import CaseRepository, CaseRunRepository, DocumentRepository
from idp.pipeline.orchestrator import process_case_run
from idp.storage.object_store import S3ObjectStore
from tests.conftest import FIXTURES_DIR, GOLDEN_DIR, normalize_extracted_string

pytestmark = [pytest.mark.usefixtures("require_postgres", "require_minio", "require_reasoning_llm")]

_MAX_ATTEMPTS = 3


async def _run_fixture(live_settings, filename: str):
    factory = get_session_factory(live_settings)
    object_store = S3ObjectStore(live_settings)
    object_store.ensure_bucket()

    async with factory() as session:
        document_repo = DocumentRepository(session)
        case = await CaseRepository(session).create()

        document = await document_repo.create(case_id=case.id, storage_key="", original_filename=filename)
        storage_key = object_store.key_for(tenant="default", case_id=str(case.id), document_id=str(document.id), filename=filename)
        document.storage_key = storage_key
        object_store.put(storage_key, (FIXTURES_DIR / filename).read_bytes(), content_type="image/png")
        run = await CaseRunRepository(session).create_next(case, trigger="submit")
        await session.commit()

        await process_case_run(settings=live_settings, case_id=case.id, run_id=run.id)

        return await document_repo.get(document.id)


async def _run_fixture_with_retries(live_settings, filename: str, *, max_attempts: int = _MAX_ATTEMPTS):
    """Retries on non-convergence only (document.extraction is None) —
    never retries a converged-but-wrong result, since that would mask a
    real regression instead of absorbing model variance."""
    document = None
    for attempt in range(1, max_attempts + 1):
        document = await _run_fixture(live_settings, filename)
        if document.extraction is not None:
            return document, attempt
        assert document.status in ("needs_review", "failed"), (
            f"non-convergent extraction left document in unexpected status {document.status!r} "
            "instead of needs_review/failed"
        )
    return document, max_attempts


@pytest.mark.asyncio
async def test_payslip_fixture_end_to_end_with_grounding_and_golden_values(live_settings):
    document, attempts = await _run_fixture_with_retries(live_settings, "boleta_pagos1.png")
    assert document is not None
    assert document.document_type == "payslip"
    assert document.extraction is not None, (
        f"extraction did not converge in {attempts} attempt(s) against a live LLM — "
        "if this fails consistently across runs, treat it as a real regression, not variance"
    )

    payload = document.extraction.payload

    for field in ("employee_name", "gross_pay", "total_deductions", "net_pay"):
        envelope = payload[field]
        assert envelope["page"] is not None
        assert envelope["source_text"], f"{field} missing grounding source_text"

    golden = json.loads((GOLDEN_DIR / "boleta_pagos1.json").read_text())
    for field, expected in golden["fields"].items():
        envelope = payload.get(field)
        if envelope is None:
            # employer_name is Optional[Extracted[str]] on PayslipSchema — the
            # agent isn't required to populate every optional field, only the
            # ones the schema marks required. A soft miss here isn't a defect.
            print(f"NOTE: optional field {field!r} was not extracted this run; skipping golden comparison for it")
            continue
        actual = envelope["value"]
        if isinstance(expected, (int, float)):
            assert abs(float(expected) - float(actual)) <= 0.5, f"{field}: expected~{expected} got {actual}"
        else:
            assert normalize_extracted_string(str(expected)) == normalize_extracted_string(str(actual))
