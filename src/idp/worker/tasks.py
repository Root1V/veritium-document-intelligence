"""Background entrypoint for one case run (FastAPI ``BackgroundTasks``). Owns
its own DB session — a background task outlives the HTTP request's DI
scope, so it cannot reuse a request-scoped session. This is the seam the
durable executor on aeon replaces in VRT-26 (``CaseExecutionPort``); the
orchestrator's signature does not change."""

from __future__ import annotations

import uuid

from idp.config import Settings
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import ReferenceDataRepository
from idp.pipeline.orchestrator import process_case_run
from idp.storage.object_store import S3ObjectStore
from idp.validation.ports import StubExternalSystemPort


async def run_case(settings: Settings, case_id: uuid.UUID, run_id: uuid.UUID) -> None:
    factory = get_session_factory(settings)
    object_store = S3ObjectStore(settings)
    async with factory() as session:
        await process_case_run(
            settings=settings,
            session=session,
            case_id=case_id,
            run_id=run_id,
            object_store=object_store,
            reference_data=ReferenceDataRepository(session),
            external_system=StubExternalSystemPort(),
        )
