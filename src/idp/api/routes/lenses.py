"""Lenses of Risk and Legal (VRT-45).
GET  /v1/lenses                         the lenses
PUT  /v1/lenses/{key}                   create or edit one (admin): its playbook is Legal's to keep
GET  /v1/cases/{id}/lenses              the lenses that apply to a case, with their latest reading
POST /v1/cases/{id}/lenses/{key}        read the case through a lens (202)"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_current_user, get_db_session, require_role
from idp.config import Settings
from idp.domain.lenses import LensDefinition, LensOutput
from idp.persistence.models import LensResult, User
from idp.persistence.repositories import CaseRepository, LensRepository
from idp.pipeline.lenses import run_lens

router = APIRouter(prefix="/v1", tags=["lenses"], dependencies=[Depends(get_current_user)])


class LensResultView(BaseModel):
    id: uuid.UUID
    lens_key: str
    status: str
    output: LensOutput | None
    model: str | None
    error: str | None
    created_by: str
    created_at: datetime
    finished_at: datetime | None
    # True when the lens was edited after this reading.
    outdated: bool


class CaseLens(BaseModel):
    lens: LensDefinition
    applicable: bool  # the case has a document the lens reads
    latest: LensResultView | None


def _result_view(row: LensResult, current: LensDefinition | None) -> LensResultView:
    return LensResultView(
        id=row.id, lens_key=row.lens_key, status=row.status, output=LensOutput.model_validate(row.output) if row.output else None,
        model=row.model, error=row.error, created_by=row.created_by, created_at=row.created_at, finished_at=row.finished_at,
        outdated=current is not None and current.model_dump(mode="json") != row.definition,
    )


@router.get("/lenses", response_model=list[LensDefinition])
async def list_lenses(session: AsyncSession = Depends(get_db_session)) -> list[LensDefinition]:
    return await LensRepository(session).list_lenses()


@router.put("/lenses/{key}", response_model=LensDefinition, dependencies=[Depends(require_role("admin"))])
async def save_lens(key: str, lens: LensDefinition, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)) -> LensDefinition:
    if lens.key != key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="la clave del cuerpo no coincide con la de la ruta")
    await LensRepository(session).save(lens, by=user.name)
    await session.commit()
    return lens


@router.get("/cases/{case_id}/lenses", response_model=list[CaseLens])
async def case_lenses(case_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> list[CaseLens]:
    case = await CaseRepository(session).get(case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    repo = LensRepository(session)
    types = {d.document_type for d in case.documents if d.status != "failed"}
    results = await repo.results_for_case(case_id)
    out = []
    for lens in await repo.list_lenses():
        latest = next((r for r in results if r.lens_key == lens.key), None)
        out.append(
            CaseLens(
                lens=lens,
                applicable=bool(case.documents) and (not lens.document_types or bool(types & set(lens.document_types))),
                latest=_result_view(latest, lens) if latest else None,
            )
        )
    return out


@router.post(
    "/cases/{case_id}/lenses/{key}",
    response_model=LensResultView,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role("operador", "admin"))],
)
async def read_with_lens(
    case_id: uuid.UUID,
    key: str,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(get_current_user),
) -> LensResultView:
    if await CaseRepository(session).get(case_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    repo = LensRepository(session)
    lens = await repo.get(key)
    if lens is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"la lente '{key}' no existe")
    if any(r.lens_key == key and r.status == "running" for r in await repo.results_for_case(case_id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="esta lente ya está leyendo el expediente")
    row = LensResult(case_id=case_id, lens_key=key, definition=lens.model_dump(mode="json"), created_by=user.name)
    session.add(row)
    await session.commit()
    background.add_task(run_lens, settings, row.id)
    return _result_view(row, lens)
