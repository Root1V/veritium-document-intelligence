"""Response models shared across more than one router — kept out of any
single ``routes/*.py`` file so neither has to import from the other."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


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
