from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from idp.config import Settings
from idp.domain.request_payload import RequestInputPayload
from idp.validation.context import DocumentFields, ValidationContext
from idp.validation.ports import InMemoryReferenceDataPort, StubExternalSystemPort

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "documents"
GOLDEN_DIR = Path(__file__).parent / "golden" / "expected_extractions"


def normalize_extracted_string(value: str) -> str:
    """Strips leading label-separator artifacts (a stray ':' or '-' from an
    OCR region that bled in from an adjacent field label) and collapses
    whitespace, so golden comparisons check semantic equivalence rather than
    byte-exact OCR formatting."""
    return value.strip().lstrip(":-").strip().lower()


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def golden():
    def _load(name: str) -> dict:
        return json.loads((GOLDEN_DIR / f"{name}.json").read_text())

    return _load


def make_document_fields(document_type: str, fields: dict, document_id: uuid.UUID | None = None) -> DocumentFields:
    return DocumentFields(document_id=document_id or uuid.uuid4(), document_type=document_type, fields=fields)


def make_context(
    current: DocumentFields,
    *,
    siblings: list[DocumentFields] | None = None,
    request_payload: dict | None = None,
    reference_employees: dict[str, str] | None = None,
) -> ValidationContext:
    return ValidationContext(
        case_id=uuid.uuid4(),
        current_document=current,
        sibling_documents=siblings or [],
        request_payload=RequestInputPayload(data=request_payload or {}),
        reference_data=InMemoryReferenceDataPort(reference_employees or {}),
        external_system=StubExternalSystemPort(),
    )
