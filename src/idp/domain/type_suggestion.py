"""Value objects for the type-discovery step: when a document falls into
``generic``, this is the LLM's structured judgment about whether its
content looks like a stable, recurring business document type worth
promoting to a first-class ``DocumentType`` — the same call a human
operator has made by hand for every type in ``domain/schemas/`` so far
(see each schema's promotion docstring). A human still decides whether to
accept the proposal (``api/routes/type_suggestions.py``); this module only
drafts it — the platform never registers a new ``DocumentType`` on its own.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SuggestedFieldType = Literal["str", "int", "float", "bool", "list"]


class SuggestedField(BaseModel):
    name: str = Field(description="Field name in English snake_case, following the convention of the existing schemas.")
    field_type: SuggestedFieldType
    description: str = Field(
        description=(
            "Description in Spanish of what the field represents and where it is extracted from — it must be explicit: "
            "fields without a clear description are systematically missed by the extraction."
        )
    )
    required: bool = Field(description="Whether the field is consistently present (True) or only sometimes (False).")


class DocumentTypeProposal(BaseModel):
    is_promotable: bool = Field(
        description=(
            "True only if the content has a stable, repeatable business form that deserves its own type. "
            "False if the document is too unique, noisy, or its content has no clear structure worth "
            "standardizing."
        )
    )
    suggested_type_name: str | None = Field(
        default=None, description="English snake_case, following the convention of the existing document types (e.g. 'debt_capacity_calculation')."
    )
    suggested_display_name: str | None = Field(default=None, description="Readable name in Spanish (e.g. 'Calculadora de Capacidad de Endeudamiento').")
    rationale: str = Field(description="In Spanish: why this document deserves (or not) its own type, and how it differs from the types the platform already knows.")
    fields: list[SuggestedField] = Field(default_factory=list, description="Proposed fields for the new type's schema — empty if is_promotable is False.")
