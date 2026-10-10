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


def _names(text: str, label: str) -> bool:
    """Whether the answer names the case (the model may write EXP‑123 with a non-breaking hyphen)."""
    return label.casefold() in text.replace("\u2011", "-").replace("\u2010", "-").casefold()


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
    found = (await session.scalars(select(Case).where(Case.id.in_(reply.seen)))).all()
    labels = {c.id: c.external_ref or f"Expediente {str(c.id)[:8]}" for c in found}
    # A person reads case names, not ids: an id the model still wrote becomes the case's name, or goes.
    answer = assistant.UUID.sub(lambda m: labels.get(uuid.UUID(m.group()), ""), reply.answer)
    # A link for each case its tools returned that the answer names — never one it made up.
    cases = [CaseLink(id=i, label=labels[i]) for i in reply.seen if i in labels and _names(answer, labels[i])]
    return AssistantResponse(answer=answer, cases=cases, consulted=reply.consulted)
