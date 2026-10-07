"""GET /type-suggestions (pending queue), PATCH /type-suggestions/{id} (edit
a still-pending proposal), and POST /type-suggestions/{id}/accept or
/reject — a human decides whether a drafted ``DocumentType`` proposal (see
``classification/type_discovery.py``) gets promoted. PATCH lets a reviewer
refine what the LLM drafted (rename/retype/add/remove fields, adjust the
suggested type name) before deciding — it only ever touches the DB row,
never code. Accepting only marks the proposal actionable; it does NOT
register the type in ``domain/document_types.py`` — turning an accepted
proposal into a real, registered ``DocumentType`` (schema + extractor +
prompts) remains a deliberate code change, same as every type added to
this platform so far."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, require_role
from idp.persistence.models import DocumentTypeSuggestion, User
from idp.persistence.repositories import TypeSuggestionRepository

router = APIRouter(prefix="/type-suggestions", tags=["type-suggestions"], dependencies=[Depends(get_current_user)])

_TYPE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class SuggestedFieldResponse(BaseModel):
    name: str
    field_type: str
    description: str
    required: bool


class TypeSuggestionResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    batch_id: uuid.UUID
    suggested_type_name: str
    suggested_display_name: str
    rationale: str
    fields: list[dict]
    status: str
    reviewer_identity: str | None


class SuggestedFieldUpdate(BaseModel):
    name: str
    field_type: Literal["str", "int", "float", "bool", "list"]
    description: str
    required: bool

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field name cannot be blank")
        return value


class UpdateTypeSuggestionRequest(BaseModel):
    suggested_type_name: str | None = None
    suggested_display_name: str | None = None
    fields: list[SuggestedFieldUpdate] | None = None

    @field_validator("suggested_type_name")
    @classmethod
    def _valid_type_name(cls, value: str | None) -> str | None:
        if value is not None and not _TYPE_NAME_PATTERN.match(value):
            raise ValueError("suggested_type_name must be snake_case (e.g. 'debt_capacity_calculation')")
        return value

    @field_validator("suggested_display_name")
    @classmethod
    def _display_name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("suggested_display_name cannot be blank")
        return value


def _to_response(row: DocumentTypeSuggestion) -> TypeSuggestionResponse:
    return TypeSuggestionResponse(
        id=row.id,
        document_id=row.document_id,
        batch_id=row.case_id,
        suggested_type_name=row.suggested_type_name,
        suggested_display_name=row.suggested_display_name,
        rationale=row.rationale,
        fields=row.fields,
        status=row.status,
        reviewer_identity=row.reviewer_identity,
    )


@router.get("", response_model=list[TypeSuggestionResponse])
async def list_pending_suggestions(session: AsyncSession = Depends(get_db_session)) -> list[TypeSuggestionResponse]:
    repo = TypeSuggestionRepository(session)
    rows = await repo.list_pending()
    return [_to_response(row) for row in rows]


@router.patch("/{suggestion_id}", response_model=TypeSuggestionResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def update_suggestion(
    suggestion_id: uuid.UUID,
    body: UpdateTypeSuggestionRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TypeSuggestionResponse:
    repo = TypeSuggestionRepository(session)
    row = await repo.get(suggestion_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="type suggestion not found")
    if row.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only a pending suggestion can be edited")

    fields = [f.model_dump() for f in body.fields] if body.fields is not None else None
    if fields is not None:
        names = [f["name"] for f in fields]
        if len(names) != len(set(names)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="field names must be unique")

    row = await repo.update(
        suggestion_id,
        suggested_type_name=body.suggested_type_name,
        suggested_display_name=body.suggested_display_name,
        fields=fields,
    )
    await session.commit()
    return _to_response(row)


async def _resolve(suggestion_id: uuid.UUID, decision: str, reviewer_identity: str, session: AsyncSession) -> TypeSuggestionResponse:
    repo = TypeSuggestionRepository(session)
    row = await repo.get(suggestion_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="type suggestion not found")
    row = await repo.resolve(suggestion_id, decision=decision, reviewer_identity=reviewer_identity)
    await session.commit()
    return _to_response(row)


@router.post("/{suggestion_id}/accept", response_model=TypeSuggestionResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def accept_suggestion(
    suggestion_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> TypeSuggestionResponse:
    return await _resolve(suggestion_id, "accepted", current_user.name, session)


@router.post("/{suggestion_id}/reject", response_model=TypeSuggestionResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def reject_suggestion(
    suggestion_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> TypeSuggestionResponse:
    return await _resolve(suggestion_id, "rejected", current_user.name, session)
