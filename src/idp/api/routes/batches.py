"""Legacy v0 API, kept for the current web UI (ADR-0002): POST /batches
(upload), GET /batches/{id} (status + documents), GET /batches/{id}/stream
(the same payload over SSE — see stream_batch for why it polls the DB
server-side) and GET /batches/{id}/entities. A "batch" is a case (VRT-25)
under the built-in ``ad-hoc`` profile; the JSON keeps its v0 field names.
Integrations use /v1/cases."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_current_user, get_db_session, get_object_store, require_role
from idp.api.schemas import DocumentSummary
from idp.config import Settings
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case
from idp.api.case_service import dispatch_run, open_run, read_uploads, resolve_profile_version, store_uploads
from idp.domain.process_profile_seed import AD_HOC_KEY
from idp.domain.semantic_resolution import ConsolidatedView
from idp.persistence.repositories import CaseRepository, DocumentRepository
from idp.pipeline.orchestrator import case_document_fields, resolve_semantic_view
from idp.storage.object_store import S3ObjectStore

router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(get_current_user)])

_STREAM_POLL_SECONDS = 1.0
_TERMINAL_BATCH_STATUSES = {"completed", "failed"}


class BatchStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    documents: list[DocumentSummary]


class BatchCreateResponse(BaseModel):
    batch_id: uuid.UUID


def _to_response(case: Case) -> BatchStatusResponse:
    return BatchStatusResponse(
        id=case.id,
        status=case.status,
        documents=[
            DocumentSummary(
                id=doc.id,
                batch_id=doc.case_id,
                status=doc.status,
                document_type=doc.document_type,
                classification_confidence=doc.classification_confidence,
                needs_review=doc.needs_review,
                original_filename=doc.original_filename,
                parent_document_id=doc.parent_document_id,
                page_start=doc.page_start,
                page_end=doc.page_end,
            )
            for doc in case.documents
        ],
    )


@router.post("", response_model=BatchCreateResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_role("operador", "admin"))])
async def create_batch(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(...)],
    request_input_payload: Annotated[str | None, Form()] = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    object_store: S3ObjectStore = Depends(get_object_store),
) -> BatchCreateResponse:
    payload_dict = json.loads(request_input_payload) if request_input_payload else None
    uploads = await read_uploads(files)
    ad_hoc = await resolve_profile_version(session, AD_HOC_KEY, None)
    case = await CaseRepository(session).create(request_input_payload=payload_dict, profile_version_id=ad_hoc.id)
    await store_uploads(session, object_store, case, uploads)
    run = await open_run(session, case, trigger="submit")
    await session.commit()

    await dispatch_run(session, settings, case, run, background_tasks)

    return BatchCreateResponse(batch_id=case.id)


@router.get("/{batch_id}", response_model=BatchStatusResponse)
async def get_batch(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> BatchStatusResponse:
    case = await CaseRepository(session).get(batch_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch not found")
    return _to_response(case)


@router.get("/{batch_id}/stream")
async def stream_batch(
    batch_id: uuid.UUID,
    request: Request,
    settings: Settings = Depends(get_app_settings),
) -> StreamingResponse:
    """Server-Sent Events alternative to polling GET /batches/{id} every 2s
    from the client. Deliberately NOT a real-time push wired directly from
    orchestrator.py (e.g. an in-process pub/sub notified on every
    ``set_status`` call) — that would only work correctly with a single
    worker process and adds a fair amount of machinery for a UI-responsiveness
    win. Polling the DB every second from inside the generator and only
    emitting a frame when the payload actually changed gets the same
    practical result (one persistent connection instead of a new HTTP
    request every 2s, sub-2s latency) with no new moving parts; this is the
    seam to swap for real push later if that ever proves insufficient.

    Auth still goes through ``get_current_user`` like every other route
    here (see the router's ``dependencies=``) — the frontend connects with
    ``fetch`` + a manual ``Authorization`` header instead of the browser's
    native ``EventSource`` specifically because ``EventSource`` cannot set
    custom headers, and putting the JWT in the URL as a query param
    instead would leak it into server access logs."""

    async def event_generator() -> AsyncIterator[str]:
        factory = get_session_factory(settings)
        last_payload: str | None = None
        while True:
            if await request.is_disconnected():
                return
            async with factory() as session:
                case = await CaseRepository(session).get(batch_id)
            if case is None:
                return
            payload = _to_response(case).model_dump_json()
            is_terminal = case.status in _TERMINAL_BATCH_STATUSES
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if is_terminal:
                return
            await asyncio.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{batch_id}/entities", response_model=ConsolidatedView)
async def get_batch_entities(batch_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> ConsolidatedView:
    """The batch's consolidated semantic view (VRT-23): for each role and
    attribute, the resolved value, whether the documents agree, and the
    evidence per source. Becomes the `entities` section of the case result
    contract in VRT-25."""
    case = await CaseRepository(session).get(batch_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="batch not found")
    catalog_version = case.profile_version.semantic_catalog_version if case.profile_version is not None else None
    view = await resolve_semantic_view(session, await case_document_fields(DocumentRepository(session), batch_id), catalog_version=catalog_version)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no published semantic catalog")
    return view

