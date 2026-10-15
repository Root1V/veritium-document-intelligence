"""GET/POST/PATCH /v1/tenants — the business units (VRT-57), for admins.

Registering a unit opens it to no one: who works in it, and with which
role, comes from the identity provider's groups "<prefix>:<unit>:<role>"
(or from Usuarios, for accounts kept in Veritium). So each unit lists the
groups to create there. Units are not deleted: their data would go with them."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_db_session, require_role
from idp.auth.oidc import ROLES
from idp.config import Settings
from idp.persistence import tenancy
from idp.persistence.models import Membership, Tenant
from idp.persistence.repositories import register_tenant

router = APIRouter(prefix="/v1/tenants", tags=["tenants"], dependencies=[Depends(require_role("admin"))])


class UnitView(BaseModel):
    key: str
    name: str
    people: int
    groups: list[str]  # to create in the identity provider, one per role
    created_at: datetime


class UnitRequest(BaseModel):
    key: str = Field(description="Identificador: minúsculas, dígitos y guiones; va en los grupos y no cambia.")
    name: str = Field(min_length=2, max_length=256)


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
    """A new unit, with the seed processes to start from."""
    if not tenancy.valid_key(body.key):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="el identificador admite minúsculas, dígitos y guiones (hasta 63)")
    if await session.get(Tenant, body.key) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ya existe una unidad con ese identificador")
    unit = await register_tenant(session, body.key, body.name.strip())
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
