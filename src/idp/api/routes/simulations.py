"""What-if simulation and shadow mode (VRT-44) — what would change if a
profile version (usually a draft) were the one in use.
GET  /v1/simulations              list, newest first
POST /v1/simulations              what_if over past cases (202), or start a shadow
GET  /v1/simulations/{id}         summary and the cases that change
POST /v1/simulations/{id}/stop    stop a shadow
Admins only: it is how a profile change is checked before publishing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from idp.api.deps import get_app_settings, get_current_user, get_db_session, require_role
from idp.config import Settings
from idp.domain.simulation import Outcome, SimulationSummary, summarize
from idp.persistence.models import Simulation, SimulationResult, User
from idp.persistence.repositories import ProcessProfileRepository
from idp.pipeline.simulation import run_what_if

router = APIRouter(prefix="/v1/simulations", tags=["simulations"], dependencies=[Depends(get_current_user)])
_admin = [Depends(require_role("admin"))]


class SimulationRequest(BaseModel):
    profile_key: str
    profile_version: int = Field(description="La versión candidata, normalmente el borrador.")
    kind: Literal["what_if", "shadow"] = "what_if"
    case_limit: int = Field(default=50, ge=1, le=500, description="what_if: cuántos expedientes pasados, los más recientes.")


class SimulationView(BaseModel):
    id: uuid.UUID
    kind: str
    profile_key: str
    profile_version: int
    profile_version_status: str
    case_limit: int | None
    status: str
    error: str | None
    created_by: str
    created_at: datetime
    finished_at: datetime | None
    summary: SimulationSummary


class CaseChange(BaseModel):
    case_id: uuid.UUID
    case_ref: str | None
    actual_verdict: str | None
    simulated_verdict: str | None
    added_reasons: list[str]
    removed_reasons: list[str]
    error: str | None
    decided_at: datetime


class SimulationDetail(SimulationView):
    cases: list[CaseChange]


def _view(simulation: Simulation) -> SimulationView:
    outcomes = [Outcome(actual_verdict=r.actual_verdict, simulated_verdict=r.simulated_verdict, failed=r.error is not None) for r in simulation.results]
    return SimulationView(
        id=simulation.id, kind=simulation.kind, profile_key=simulation.profile_key, profile_version=simulation.profile_version.version,
        profile_version_status=simulation.profile_version.status, case_limit=simulation.case_limit, status=simulation.status, error=simulation.error,
        created_by=simulation.created_by, created_at=simulation.created_at, finished_at=simulation.finished_at, summary=summarize(outcomes),
    )


async def _get(session: AsyncSession, simulation_id: uuid.UUID) -> Simulation:
    stmt = (
        select(Simulation)
        .where(Simulation.id == simulation_id)
        .options(selectinload(Simulation.results).selectinload(SimulationResult.case), selectinload(Simulation.profile_version))
        .execution_options(populate_existing=True)
    )
    simulation = await session.scalar(stmt)
    if simulation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="simulation not found")
    return simulation


@router.get("", response_model=list[SimulationView])
async def list_simulations(session: AsyncSession = Depends(get_db_session)) -> list[SimulationView]:
    stmt = select(Simulation).options(selectinload(Simulation.results), selectinload(Simulation.profile_version)).order_by(Simulation.created_at.desc())
    return [_view(s) for s in (await session.scalars(stmt)).all()]


@router.post("", response_model=SimulationView, status_code=status.HTTP_202_ACCEPTED, dependencies=_admin)
async def start(
    body: SimulationRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(get_current_user),
) -> SimulationView:
    repo = ProcessProfileRepository(session)
    profile = await repo.get_by_key(body.profile_key)
    version = await repo.get_version(profile, body.profile_version) if profile else None
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"el perfil '{body.profile_key}' no tiene la versión {body.profile_version}")
    if body.kind == "shadow":
        # One shadow per profile: a new candidate replaces the previous one.
        await session.execute(
            update(Simulation)
            .where(Simulation.kind == "shadow", Simulation.status == "running", Simulation.profile_key == body.profile_key)
            .values(status="stopped", finished_at=datetime.now(UTC))
        )
    simulation = Simulation(
        kind=body.kind, profile_key=body.profile_key, profile_version_id=version.id, created_by=user.name,
        case_limit=body.case_limit if body.kind == "what_if" else None, status="pending" if body.kind == "what_if" else "running",
    )
    session.add(simulation)
    await session.commit()
    if body.kind == "what_if":
        background.add_task(run_what_if, settings, simulation.id)
    return _view(await _get(session, simulation.id))


@router.get("/{simulation_id}", response_model=SimulationDetail)
async def get_simulation(simulation_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> SimulationDetail:
    simulation = await _get(session, simulation_id)
    results = sorted(simulation.results, key=lambda r: (r.actual_verdict == r.simulated_verdict and r.error is None, -r.created_at.timestamp()))
    return SimulationDetail(
        **_view(simulation).model_dump(),
        cases=[
            CaseChange(
                case_id=r.case_id, case_ref=r.case.external_ref, actual_verdict=r.actual_verdict, simulated_verdict=r.simulated_verdict,
                added_reasons=r.added_reasons, removed_reasons=r.removed_reasons, error=r.error, decided_at=r.created_at,
            )
            for r in results
        ],
    )


@router.post("/{simulation_id}/stop", response_model=SimulationView, dependencies=_admin)
async def stop(simulation_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> SimulationView:
    simulation = await _get(session, simulation_id)
    if simulation.kind != "shadow" or simulation.status != "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="solo se detiene una simulación en sombra en curso")
    simulation.status, simulation.finished_at = "stopped", datetime.now(UTC)
    await session.commit()
    return _view(await _get(session, simulation_id))
