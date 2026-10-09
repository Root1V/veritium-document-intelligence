"""The instructions the platform gives the models (VRT-46), read only.
GET /v1/prompts   each prompt: what it is for, its version in use, its text,
                  since when, how many runs used it, and its earlier versions
Editing them, governed, is VRT-63."""

from __future__ import annotations

import string
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session
from idp.llm.prompts import INFO, current
from idp.persistence.repositories import PromptRepository

router = APIRouter(prefix="/v1/prompts", tags=["prompts"], dependencies=[Depends(get_current_user)])


class PromptVersionView(BaseModel):
    version: str
    text: str
    first_seen_at: datetime | None
    runs: int


class PromptView(BaseModel):
    name: str
    label: str
    purpose: str
    version: str
    text: str
    # What the platform fills in each time: the parts of the text that change per call.
    placeholders: list[str]
    since: datetime | None
    runs: int
    earlier: list[PromptVersionView]


@router.get("", response_model=list[PromptView])
async def list_prompts(session: AsyncSession = Depends(get_db_session)) -> list[PromptView]:
    repo = PromptRepository(session)
    history = await repo.history()
    usage = await repo.usage()
    out = []
    order = list(INFO)  # the order of the process: classify, segment, extract…
    for p in sorted(current(), key=lambda p: order.index(p.name) if p.name in order else len(order)):
        label, purpose = INFO.get(p.name, (p.name, ""))
        versions = [h for h in history if h.name == p.name]
        this = next((h for h in versions if h.version == p.version), None)
        out.append(
            PromptView(
                name=p.name,
                label=label,
                purpose=purpose,
                version=p.version,
                text=p.text,
                placeholders=sorted(_placeholders(p.text)),
                since=_since(this.first_seen_at if this else None, usage.get((p.name, p.version))),
                runs=usage.get((p.name, p.version), (0, None))[0],
                earlier=[
                    PromptVersionView(
                        version=h.version, text=h.text, first_seen_at=_since(h.first_seen_at, usage.get((p.name, h.version))),
                        runs=usage.get((p.name, h.version), (0, None))[0],
                    )
                    for h in versions
                    if h.version != p.version
                ],
            )
        )
    return out


def _since(kept: datetime | None, used: tuple[int, datetime] | None) -> datetime | None:
    """Since when a version is in use: when it was kept, or the first run
    that used it, if that was earlier (runs from before versions were kept)."""
    dates = [d for d in (kept, used[1] if used else None) if d is not None]
    return min(dates) if dates else None


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}
