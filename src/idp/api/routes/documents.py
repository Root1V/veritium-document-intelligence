"""GET /documents/{id} — extraction payload (with citations + reasoning_trace)
plus validation issues (with explanation), per the explainability design.
Personal data masked unless the caller asked to see the case's (VRT-58);
the original file only then, and searching by a value only for whoever may
see them. DELETE /documents/{id} removes one for good and re-evaluates its
case (admin; VRT-72)."""

from __future__ import annotations

import mimetypes
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.case_service import dispatch_run, open_run
from idp.api.deps import get_app_settings, get_current_user, get_db_session, get_object_store, get_principal, require_role
from idp.api.disclosure import CaseMaskers, Disclosure, actor_of, can_reveal, get_disclosure, record, window_open
from idp.auth.authenticate import Principal
from idp.api.schemas import DocumentSummary, SearchMatch
from idp.config import Settings
from idp.persistence.models import Case
from idp.persistence.repositories import CaseRepository, DocumentRepository
from idp.pipeline.deletion import delete_document, purge
from idp.pipeline.retention import CaseBusy
from idp.search.models import search_models
from idp.search.query import Filters, Hit, search
from idp.storage.object_store import S3ObjectStore

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(get_current_user)])


class ValidationIssueResponse(BaseModel):
    rule_id: str
    category: str
    field_path: str | None
    severity: str
    message: str
    confidence: float
    confidence_method: str
    explanation: str


class DocumentDetailResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    status: str
    document_type: str | None
    classification_confidence: float | None
    needs_review: bool
    original_filename: str
    parent_document_id: uuid.UUID | None
    page_start: int | None
    page_end: int | None
    extraction: dict | None
    validation_issues: list[ValidationIssueResponse]
    personal_data_visible: bool  # VRT-58: false = masked; the original file needs them visible
    can_reveal: bool  # the caller's role may ask to see them (POST /v1/cases/{case_id}/reveal)


class DocumentListResponse(BaseModel):
    total: int
    documents: list[DocumentSummary]


def _match(hit: Hit) -> SearchMatch:
    return SearchMatch(where=hit.kind, page=hit.page + 1 if hit.page is not None else None)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    status_: Annotated[str | None, Query(alias="status")] = None,
    document_type: str | None = None,
    needs_review: bool | None = None,
    profile: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_app_settings),
) -> DocumentListResponse:
    """The documents, newest first; with ``q``, the ones that match it, best
    first (VRT-59), each saying where it matched — never what it says."""
    filters = Filters(status=status_, document_type=document_type, needs_review=needs_review, profile=profile)
    repo = DocumentRepository(session)
    matches: dict[uuid.UUID, Hit] = {}
    if q and q.strip():  # finding a case by a DNI or a name is seeing personal data
        if not can_reveal(principal.role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tu rol no permite buscar por datos personales")
        await record(session, principal, action="buscar", what="búsqueda de documentos por un dato")  # the term is not kept: it is the datum
        hits = await search(session, search_models(settings), q, filters)
        matches = {h.document_id: h for h in hits}
        documents = await repo.get_many([h.document_id for h in hits[offset : offset + limit]])
        total = len(hits)
    else:
        documents = await repo.list(filters, limit=limit, offset=offset)
        total = await repo.count(filters)
    maskers = CaseMaskers(session, principal)
    case_ids = {doc.case_id for doc in documents}
    refs = dict((await session.execute(select(Case.id, Case.external_ref).where(Case.id.in_(case_ids)))).all()) if case_ids else {}
    return DocumentListResponse(
        total=total,
        documents=[
            DocumentSummary(
                id=doc.id,
                batch_id=doc.case_id,
                status=doc.status,
                document_type=doc.document_type,
                classification_confidence=doc.classification_confidence,
                needs_review=doc.needs_review,
                original_filename=(await maskers(doc.case_id)).text(doc.original_filename),
                parent_document_id=doc.parent_document_id,
                page_start=doc.page_start,
                page_end=doc.page_end,
                match=_match(matches[doc.id]) if doc.id in matches else None,
                case_ref=refs.get(doc.case_id),
                created_at=doc.created_at,
            )
            for doc in documents
        ],
    )


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    object_store: S3ObjectStore = Depends(get_object_store),
    disclosure: Disclosure = Depends(get_disclosure),
) -> Response:
    """The original is all personal data: only after asking to see the case's, recorded."""
    repo = DocumentRepository(session)
    document = await repo.get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    if not await window_open(session, disclosure.principal, document.case_id):
        if not disclosure.reveal:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="el documento original muestra datos personales: pide verlos primero (Ver datos)")
        await record(session, disclosure.principal, action="descargar_original", what="documento original", case_id=document.case_id, document_id=document.id)
    content = object_store.get(document.storage_key)
    content_type = mimetypes.guess_type(document.original_filename)[0] or "application/octet-stream"
    return Response(content=content, media_type=content_type)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role("admin"))])
async def delete_document_for_good(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(get_principal),
    object_store: S3ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    """Delete a document (e.g. uploaded by mistake) with its file and what was
    read from it; a new run re-evaluates the case without it, so its verdict
    and what it lacks are current."""
    document = await DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    case = await CaseRepository(session).get(document.case_id)
    if case.anonymized_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="los datos de este expediente se suprimieron: elimina el expediente completo")
    try:
        keys = await delete_document(session, document, actor=actor_of(principal), role=principal.role, channel="api" if principal.client else "web")
    except CaseBusy as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await purge(session, object_store, keys)
    case = await CaseRepository(session).get(case.id)
    run = await open_run(session, case, trigger="document_removed")
    await session.commit()
    await dispatch_run(session, settings, case, run, background_tasks)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: uuid.UUID, session: AsyncSession = Depends(get_db_session), disclosure: Disclosure = Depends(get_disclosure)
) -> DocumentDetailResponse:
    repo = DocumentRepository(session)
    document = await repo.get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    case = await CaseRepository(session).get(document.case_id)
    masker = await disclosure.masker(session, case, what="documento", document_id=document.id)

    detail = DocumentDetailResponse(
        id=document.id,
        case_id=document.case_id,
        status=document.status,
        document_type=document.document_type,
        classification_confidence=document.classification_confidence,
        needs_review=document.needs_review,
        original_filename=document.original_filename,
        parent_document_id=document.parent_document_id,
        page_start=document.page_start,
        page_end=document.page_end,
        extraction=document.extraction.payload if document.extraction else None,
        validation_issues=[
            ValidationIssueResponse(
                rule_id=issue.rule_id,
                category=issue.category,
                field_path=issue.field_path,
                severity=issue.severity,
                message=issue.message,
                confidence=issue.confidence,
                confidence_method=issue.confidence_method,
                explanation=issue.explanation,
            )
            for issue in document.active_validation_issues
        ],
        personal_data_visible=not masker.active,
        can_reveal=can_reveal(disclosure.principal.role),
    )
    return DocumentDetailResponse.model_validate(masker.json(detail.model_dump(mode="json")))
