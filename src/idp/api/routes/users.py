"""GET/POST /users — admin-only. Lets an admin create teammates with a role
(admin | operador | visor) from the UI instead of always needing shell
access to run ``scripts/create_user.py``; the script remains the way to
bootstrap the very first admin."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_db_session, require_role
from idp.auth.security import hash_password
from idp.persistence.models import User
from idp.persistence.repositories import UserRepository

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_role("admin"))])

ROLES = {"admin", "operador", "visor", "integracion", "especialista_ia"}


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str


class CreateUserRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "operador"


def _to_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, name=user.name, email=user.email, role=user.role)


@router.get("", response_model=list[UserResponse])
async def list_users(session: AsyncSession = Depends(get_db_session)) -> list[UserResponse]:
    users = await UserRepository(session).list()
    return [_to_response(u) for u in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: CreateUserRequest, session: AsyncSession = Depends(get_db_session)) -> UserResponse:
    if body.role not in ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"role must be one of {sorted(ROLES)}")
    repo = UserRepository(session)
    if await repo.get_by_email(body.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="a user with this email already exists")
    user = await repo.create(name=body.name, email=body.email, password_hash=hash_password(body.password), role=body.role)
    await session.commit()
    return _to_response(user)
