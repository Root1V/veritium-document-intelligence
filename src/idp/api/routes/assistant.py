"""The user's assistant (VRT-54).

POST /v1/assistant/messages   answer the last question of a conversation

The conversation lives in the client: each call carries it whole, and the
server keeps nothing. The assistant reaches the data through Veritium's
MCP server with the caller's own token (idp/assistant.py)."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp import assistant
from idp.api.deps import get_app_settings, get_current_user, get_db_session
from idp.config import Settings
from idp.persistence.models import Case

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/assistant", tags=["assistant"], dependencies=[Depends(get_current_user)])


class AssistantRequest(BaseModel):
    conversation: list[assistant.Turn] = Field(min_length=1, max_length=40)
    case_id: uuid.UUID | None = None  # the case the person is looking at, if any


class CaseLink(BaseModel):
    id: uuid.UUID
    label: str


class AssistantResponse(BaseModel):
    answer: str
    cases: list[CaseLink]
    consulted: list[str]


@router.post("/messages", response_model=AssistantResponse)
async def ask(
    body: AssistantRequest,
    settings: Annotated[Settings, Depends(get_app_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())],
) -> AssistantResponse:
    if body.conversation[-1].role != "user":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="el último mensaje debe ser la pregunta")
    try:
        reply = await assistant.answer(settings, credentials.credentials, body.conversation, case_id=body.case_id)
    except Exception as exc:
        log.warning("assistant: no respondió (%s: %s)", type(exc).__name__, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="El asistente no pudo responder esta vez. Intenta de nuevo.") from exc
    labels = {c.id: c.external_ref for c in (await session.scalars(select(Case).where(Case.id.in_(reply.case_ids)))).all()}
    cases = [CaseLink(id=i, label=labels[i] or f"Expediente {str(i)[:8]}") for i in reply.case_ids if i in labels]
    return AssistantResponse(answer=reply.answer, cases=cases, consulted=reply.consulted)
