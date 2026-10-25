"""GET/POST /users — the people of the active business unit (VRT-57),
admin-only. Lets an admin add teammates with a role (admin | operador |
visor) from the UI instead of always needing shell access to run
``scripts/create_user.py``; the script remains the way to bootstrap the very
first admin. People who sign in through the identity provider get their
units and roles from its groups: here they are only shown. DELETE
/users/{id} takes someone out of the unit (VRT-72); the person stays, so
their name in the records still says who did what. PATCH /users/{id}
changes their role in the unit (VRT-96)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, require_role
from idp.auth.security import hash_password
from idp.persistence import tenancy
from idp.persistence.models import Membership, User
from idp.persistence.repositories import UserRepository

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_role("admin"))])

ROLES = {"admin", "operador", "visor", "integracion", "especialista_ia"}


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str  # in the active unit
    managed_by: str  # "idp" (the identity provider's groups) | "local"


class CreateUserRequest(BaseModel):
    name: str
    email: str
    password: str | None = None  # only for a new person
    role: str = "operador"


class ChangeRoleRequest(BaseModel):
    role: str


def _to_response(user: User, membership: Membership) -> UserResponse:
    return UserResponse(id=user.id, name=user.name, email=user.email, role=membership.role, managed_by=membership.source)


@router.get("", response_model=list[UserResponse])
async def list_users(session: AsyncSession = Depends(get_db_session)) -> list[UserResponse]:
    return [_to_response(u, m) for u, m in await UserRepository(session).members(tenancy.current())]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: CreateUserRequest, session: AsyncSession = Depends(get_db_session)) -> UserResponse:
    """A new person, or someone who already works in another unit, into this one."""
    if body.role not in ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"role must be one of {sorted(ROLES)}")
    repo, tenant = UserRepository(session), tenancy.current()
    user = await repo.get_by_email(body.email)
    if user is not None and await repo.role_in(user.id, tenant) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="a user with this email already exists")
    if user is None:
        if not body.password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="a new user needs a password")
        user = await repo.create(name=body.name, email=body.email, password_hash=hash_password(body.password))
    membership = await repo.set_membership(user.id, tenant, body.role)
    await session.commit()
    return _to_response(user, membership)


async def _local_membership(session: AsyncSession, user_id: uuid.UUID, current: User) -> Membership:
    if user_id == current.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no puedes cambiar tu propio acceso: pídeselo a otro admin")
    membership = await session.scalar(select(Membership).where(Membership.user_id == user_id, Membership.tenant == tenancy.current()))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if membership.source == "idp":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="su acceso viene del proveedor de identidad: cámbialo en su grupo allí")
    return membership


@router.patch("/{user_id}", response_model=UserResponse)
async def change_role(user_id: uuid.UUID, body: ChangeRoleRequest, session: AsyncSession = Depends(get_db_session), current: User = Depends(get_current_user)) -> UserResponse:
    if body.role not in ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"role must be one of {sorted(ROLES)}")
    membership = await _local_membership(session, user_id, current)
    membership.role = body.role
    await session.commit()
    user = await session.get(User, user_id)
    assert user is not None
    return _to_response(user, membership)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_unit(user_id: uuid.UUID, session: AsyncSession = Depends(get_db_session), current: User = Depends(get_current_user)) -> Response:
    membership = await _local_membership(session, user_id, current)
    await session.delete(membership)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
