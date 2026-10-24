"""GET/POST/PATCH /v1/tenants — the business units (VRT-57), for the
platform team (VRT-71): a unit's admin runs their unit, not the set of them.

Registering a unit opens it to no one: who works in it, and with which
role, comes from the identity provider's groups "<prefix>:<unit>:<role>"
(or from Usuarios, for accounts kept in Veritium). So each unit lists the
groups to create there. Only a unit without cases is deleted (VRT-72), with
its configuration and who worked in it; one with cases keeps them."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_db_session, require_platform
from idp.auth.oidc import PLATFORM, ROLES
from idp.config import Settings
from idp.persistence import tenancy
from idp.persistence.models import Base, Case, Membership, Tenant
from idp.persistence.repositories import register_tenant

router = APIRouter(prefix="/v1/tenants", tags=["tenants"], dependencies=[Depends(require_platform("admin"))])


class UnitView(BaseModel):
    key: str
    name: str
    people: int
    groups: list[str]  # to create in the identity provider, one per role
    created_at: datetime


class UnitRequest(BaseModel):
    key: str = Field(description="Identificador: minúsculas, dígitos y guiones; va en los grupos y no cambia.")
    name: str = Field(min_length=2, max_length=256)
    examples: bool = Field(default=False, description="Con los procesos de ejemplo; si no, empieza vacía (solo el proceso interno ad-hoc).")


class RenameRequest(BaseModel):
    name: str = Field(min_length=2, max_length=256)


def _view(settings: Settings, unit: Tenant, people: int) -> UnitView:
    order = ["admin", "operador", "visor", "especialista_ia"]
    groups = [f"{settings.oidc_group_prefix}:{unit.key}:{role}" for role in sorted(ROLES, key=order.index)]
    return UnitView(key=unit.key, name=unit.name, people=people, groups=groups, created_at=unit.created_at)


async def _people(session: AsyncSession) -> dict[str, int]:
    stmt = select(Membership.tenant, func.count()).where(Membership.role != "integracion").group_by(Membership.tenant)
    return dict((await session.execute(stmt)).all())


@router.get("", response_model=list[UnitView])
async def list_units(session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_app_settings)) -> list[UnitView]:
    people = await _people(session)
    units = (await session.scalars(select(Tenant).order_by(Tenant.name))).all()
    return [_view(settings, u, people.get(u.key, 0)) for u in units]


@router.post("", response_model=UnitView, status_code=status.HTTP_201_CREATED)
async def create_unit(body: UnitRequest, session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_app_settings)) -> UnitView:
    """A new unit: empty by default — a blank canvas — or with the example processes."""
    if not tenancy.valid_key(body.key):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="el identificador admite minúsculas, dígitos y guiones (hasta 63)")
    if body.key == PLATFORM:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"'{PLATFORM}' está reservado: sus grupos dan el rol de plataforma, no una unidad")
    if await session.get(Tenant, body.key) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ya existe una unidad con ese identificador")
    unit = await register_tenant(session, body.key, body.name.strip(), examples=body.examples)
    return _view(settings, unit, 0)


@router.patch("/{key}", response_model=UnitView)
async def rename_unit(
    key: str, body: RenameRequest, session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_app_settings)
) -> UnitView:
    """Only the name people see; the identifier is in the groups and stays."""
    unit = await session.get(Tenant, key)
    if unit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no existe esa unidad")
    unit.name = body.name.strip()
    await session.commit()
    return _view(settings, unit, (await _people(session)).get(key, 0))


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(key: str, session: AsyncSession = Depends(get_db_session)) -> Response:
    unit = await session.get(Tenant, key)
    if unit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no existe esa unidad")
    if key == tenancy.active():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="estás trabajando en esta unidad: cámbiate a otra para eliminarla")
    with tenancy.acting_for(key):
        cases = await session.scalar(select(func.count()).select_from(Case))
        if cases:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"la unidad tiene {cases} expediente(s): elimínalos primero")
        # Its configuration — processes, connected systems, webhooks, suites… — dependents first.
        for table in reversed(Base.metadata.sorted_tables):
            if "tenant" in table.c and table.name != "memberships":
                await session.execute(delete(table).where(table.c.tenant == key))
    await session.execute(delete(Membership).where(Membership.tenant == key))
    await session.delete(unit)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
