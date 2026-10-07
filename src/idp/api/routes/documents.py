"""GET /documents/{id} — extraction payload (with citations + reasoning_trace)
plus validation issues (with explanation), per the explainability design."""

from __future__ import annotations

import mimetypes
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, get_object_store
from idp.api.schemas import DocumentSummary
from idp.persistence.repositories import DocumentRepository
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


class DocumentListResponse(BaseModel):
    total: int
    documents: list[DocumentSummary]


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    status_: Annotated[str | None, Query(alias="status")] = None,
    document_type: str | None = None,
    needs_review: bool | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentListResponse:
    repo = DocumentRepository(session)
    documents = await repo.list(status=status_, document_type=document_type, needs_review=needs_review, q=q, limit=limit, offset=offset)
    total = await repo.count(status=status_, document_type=document_type, needs_review=needs_review, q=q)
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
                original_filename=doc.original_filename,
                parent_document_id=doc.parent_document_id,
                page_start=doc.page_start,
                page_end=doc.page_end,
            )
            for doc in documents
        ],
    )


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    object_store: S3ObjectStore = Depends(get_object_store),
) -> Response:
    repo = DocumentRepository(session)
    document = await repo.get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    content = object_store.get(document.storage_key)
    content_type = mimetypes.guess_type(document.original_filename)[0] or "application/octet-stream"
    return Response(content=content, media_type=content_type)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(document_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> DocumentDetailResponse:
    repo = DocumentRepository(session)
    document = await repo.get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")

    return DocumentDetailResponse(
        id=document.id,
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
    )
