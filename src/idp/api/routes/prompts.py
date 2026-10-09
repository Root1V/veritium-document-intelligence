"""The instructions the platform gives the models: read them (VRT-46) and,
for an AI specialist, change them under governance (VRT-63).
GET    /v1/prompts                          each prompt: purpose, version and text in effect, since when, runs,
                                            earlier versions, its draft and the evaluations that tried it
PUT    /v1/prompts/{name}/draft             write the draft (with its reason)
DELETE /v1/prompts/{name}/draft             discard it
POST   /v1/prompts/{name}/draft/publish     put it in effect — after an evaluation tried it, or an explicit
                                            acknowledgement for a prompt no evaluation exercises
POST   /v1/prompts/{name}/restore           back to an earlier version, or to the code's text"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, require_role
from idp.llm.prompts import EVALUATED, INFO, Prompt, current, draft_problems, fingerprint, get, set_published
from idp.persistence.models import PromptEdit, PromptVersionRecord, User
from idp.persistence.repositories import PromptEditRepository, PromptRepository

router = APIRouter(prefix="/v1/prompts", tags=["prompts"], dependencies=[Depends(get_current_user)])
_specialist = [Depends(require_role("especialista_ia"))]


class PromptVersionView(BaseModel):
    version: str
    text: str
    first_seen_at: datetime | None
    runs: int
    # Who put it in effect and why, when an AI specialist did (VRT-63).
    published_by: str | None = None
    reason: str | None = None


class DraftEvaluation(BaseModel):
    run_id: uuid.UUID
    suite_id: uuid.UUID
    suite_name: str
    status: str
    fields: dict[str, Any] | None
    created_at: datetime


class DraftView(BaseModel):
    id: uuid.UUID
    text: str
    version: str
    reason: str
    created_by: str
    created_at: datetime
    evaluations: list[DraftEvaluation]


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
    # VRT-63
    source: str  # "code" | "edited"
    code_version: str
    published_by: str | None
    published_at: datetime | None
    published_reason: str | None
    evaluated: bool  # an evaluation run exercises it, so publishing requires one
    draft: DraftView | None


class DraftRequest(BaseModel):
    text: str
    reason: str = Field(min_length=10, description="Por qué se cambia; queda en la auditoría.")


class PublishRequest(BaseModel):
    acknowledge_no_evaluation: bool = Field(default=False, description="Para instrucciones que ninguna evaluación ejercita.")


class RestoreRequest(BaseModel):
    version: str
    reason: str = Field(min_length=10)


def _since(kept: datetime | None, used: tuple[int, datetime] | None) -> datetime | None:
    """Since when a version is in use: when it was kept, or the first run
    that used it, if that was earlier (runs from before versions were kept)."""
    dates = [d for d in (kept, used[1] if used else None) if d is not None]
    return min(dates) if dates else None


async def _views(session: AsyncSession, only: str | None = None) -> list[PromptView]:
    history = await PromptRepository(session).history()
    usage = await PromptRepository(session).usage()
    edits_repo = PromptEditRepository(session)
    order = list(INFO)  # the order of the process: classify, segment, extract…
    out = []
    for p in sorted(current(), key=lambda p: order.index(p.name) if p.name in order else len(order)):
        if only is not None and p.name != only:
            continue
        label, purpose = INFO.get(p.name, (p.name, ""))
        edits = await edits_repo.for_prompt(p.name)
        published = next((e for e in edits if e.status == "published"), None)
        by_version = {e.version: e for e in reversed(edits) if e.status in ("published", "retired")}
        versions = [h for h in history if h.name == p.name]
        this = next((h for h in versions if h.version == p.version), None)
        draft = next((e for e in edits if e.status == "draft"), None)
        draft_view = None
        if draft is not None:
            runs = await edits_repo.runs_with_draft(draft.id)
            draft_view = DraftView(
                id=draft.id, text=draft.text, version=draft.version, reason=draft.reason, created_by=draft.created_by, created_at=draft.created_at,
                evaluations=[
                    DraftEvaluation(run_id=r.id, suite_id=r.suite_id, suite_name=r.suite.name, status=r.status,
                                    fields=(r.metrics or {}).get("fields"), created_at=r.created_at)
                    for r in runs
                ],
            )
        out.append(
            PromptView(
                name=p.name, label=label, purpose=purpose, version=p.version, text=p.effective,
                placeholders=list(p.filled),
                since=_since(this.first_seen_at if this else None, usage.get((p.name, p.version))),
                runs=usage.get((p.name, p.version), (0, None))[0],
                earlier=[
                    PromptVersionView(
                        version=h.version, text=h.text, first_seen_at=_since(h.first_seen_at, usage.get((p.name, h.version))),
                        runs=usage.get((p.name, h.version), (0, None))[0],
                        published_by=by_version[h.version].published_by if h.version in by_version else None,
                        reason=by_version[h.version].reason if h.version in by_version else None,
                    )
                    for h in versions
                    if h.version != p.version
                ],
                source="edited" if published else "code", code_version=p.code_version,
                published_by=published.published_by if published else None, published_at=published.published_at if published else None,
                published_reason=published.reason if published else None,
                evaluated=p.name in EVALUATED, draft=draft_view,
            )
        )
    return out


def _prompt_or_404(name: str) -> Prompt:
    prompt = get(name)
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"la instrucción '{name}' no existe")
    return prompt


async def _refresh(session: AsyncSession) -> None:
    """Put the published texts in effect in this process; the worker picks them up within a tick."""
    set_published(await PromptEditRepository(session).published_texts())


@router.get("", response_model=list[PromptView])
async def list_prompts(session: AsyncSession = Depends(get_db_session)) -> list[PromptView]:
    return await _views(session)


@router.put("/{name}/draft", response_model=PromptView, dependencies=_specialist)
async def save_draft(name: str, body: DraftRequest, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)) -> PromptView:
    prompt = _prompt_or_404(name)
    if problems := draft_problems(prompt, body.text):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(problems))
    if body.text == prompt.effective:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="el borrador es igual al texto en uso")
    await PromptEditRepository(session).save_draft(name=name, text=body.text, version=fingerprint(body.text), reason=body.reason.strip(), by=user.name)
    await session.commit()
    return (await _views(session, only=name))[0]


@router.delete("/{name}/draft", response_model=PromptView, dependencies=_specialist)
async def discard_draft(name: str, session: AsyncSession = Depends(get_db_session)) -> PromptView:
    _prompt_or_404(name)
    for edit in await PromptEditRepository(session).for_prompt(name):
        if edit.status == "draft":
            edit.status = "discarded"
    await session.commit()
    return (await _views(session, only=name))[0]


@router.post("/{name}/draft/publish", response_model=PromptView, dependencies=_specialist)
async def publish_draft(
    name: str, body: PublishRequest, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> PromptView:
    _prompt_or_404(name)
    repo = PromptEditRepository(session)
    draft = next((e for e in await repo.for_prompt(name) if e.status == "draft"), None)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no hay borrador que publicar")
    evaluation = None
    if name in EVALUATED:
        evaluation = next((r for r in await repo.runs_with_draft(draft.id) if r.status == "completed"), None)
        if evaluation is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="antes de publicar, corre una evaluación con este borrador y revisa su resultado frente a la versión en uso",
            )
    elif not body.acknowledge_no_evaluation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ninguna evaluación ejercita esta instrucción: confirma que publicas sin prueba automática",
        )
    await repo.publish(draft, by=user.name, evaluation_run_id=evaluation.id if evaluation else None)
    await session.commit()
    await _refresh(session)
    return (await _views(session, only=name))[0]


@router.post("/{name}/restore", response_model=PromptView, dependencies=_specialist)
async def restore(name: str, body: RestoreRequest, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)) -> PromptView:
    """Back to a version this prompt already had: it ran before, so it needs no new evaluation."""
    prompt = _prompt_or_404(name)
    repo = PromptEditRepository(session)
    if body.version == prompt.version:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="esa versión ya está en uso")
    if body.version == prompt.code_version:
        await repo.back_to_code(name)
    else:
        kept = await session.scalar(select(PromptVersionRecord).where(PromptVersionRecord.name == name, PromptVersionRecord.version == body.version))
        if kept is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no se conoce la versión {body.version} de esta instrucción")
        edit = PromptEdit(name=name, text=kept.text, version=kept.version, reason=f"Vuelta a la versión {kept.version}: {body.reason.strip()}", created_by=user.name)
        session.add(edit)
        await session.flush()
        await repo.publish(edit, by=user.name, evaluation_run_id=None)
    await session.commit()
    await _refresh(session)
    return (await _views(session, only=name))[0]
