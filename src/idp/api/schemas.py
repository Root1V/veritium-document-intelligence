"""Response models shared across more than one router — kept out of any
single ``routes/*.py`` file so neither has to import from the other."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SearchMatch(BaseModel):
    """Where a document matched a search (VRT-59): in its extracted values, in
    the text read from a page (1-based), or in its file name."""

    where: str  # valores | texto | archivo
    page: int | None = None


class DocumentSummary(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID  # legacy name in the v0 API; it is the case id
    status: str
    document_type: str | None
    classification_confidence: float | None
    needs_review: bool
    original_filename: str
    parent_document_id: uuid.UUID | None
    page_start: int | None
    page_end: int | None
    match: SearchMatch | None = None  # only in search results
    # Which case it is in and when it arrived (VRT-78), for the documents list.
    case_ref: str | None = None
    created_at: datetime | None = None
