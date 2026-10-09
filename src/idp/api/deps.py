"""Explicit dependency injection via FastAPI's ``Depends`` — deliberately not
module-level singletons (the PoC's ``ocr = PaddleOCR(...)`` anti-pattern)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.auth.rate_limit import limiter
from idp.auth.security import decode_claims
from idp.config import Settings, get_settings
from idp.persistence.db import get_session_factory
from idp.persistence.models import ApiClient, User
from idp.persistence.repositories import ReferenceDataRepository, UserRepository
from idp.storage.object_store import S3ObjectStore
from idp.validation.ports import ExternalSystemPort, ReferenceDataPort, StubExternalSystemPort

_bearer_scheme = HTTPBearer(auto_error=False)


def get_app_settings() -> Settings:
    return get_settings()


async def get_db_session(settings: Annotated[Settings, Depends(get_app_settings)]) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory(settings)
    async with factory() as session:
        yield session


def get_object_store(settings: Annotated[Settings, Depends(get_app_settings)]) -> S3ObjectStore:
    return S3ObjectStore(settings)


def get_reference_data_port(session: Annotated[AsyncSession, Depends(get_db_session)]) -> ReferenceDataPort:
    return ReferenceDataRepository(session)


def get_external_system_port(settings: Annotated[Settings, Depends(get_app_settings)]) -> ExternalSystemPort:
    return StubExternalSystemPort()


async def get_current_user(
    settings: Annotated[Settings, Depends(get_app_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> User:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing credentials")
    if credentials is None:
        raise unauthorized
    claims = decode_claims(settings, credentials.credentials)
    if claims is None or "sub" not in claims:
        raise unauthorized
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError:
        raise unauthorized from None
    if "cid" in claims:
        await _check_client(settings, session, claims, user_id, unauthorized)
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise unauthorized
    return user


async def _check_client(settings: Settings, session: AsyncSession, claims: dict, user_id: uuid.UUID, unauthorized: HTTPException) -> None:
    """A connected system's token (VRT-65): its client must still be active,
    the token newer than the last rotation, and the system within its quota."""
    client = await session.scalar(select(ApiClient).where(ApiClient.client_id == claims["cid"]))
    if client is None or client.revoked_at is not None or client.user_id != user_id:
        raise unauthorized
    if float(claims.get("iat", 0)) < client.secret_rotated_at.timestamp():
        raise unauthorized
    retry_after = limiter.check(client.client_id, client.rate_limit_per_minute or settings.api_client_rate_limit_per_minute)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="se superó la cuota de llamadas por minuto", headers={"Retry-After": str(retry_after)}
        )
    now = datetime.now(UTC)
    if client.last_used_at is None or now - client.last_used_at > timedelta(minutes=1):  # not one write per call
        client.last_used_at = now
        await session.commit()


def require_role(*allowed_roles: str):
    """Route-level dependency, additive to ``get_current_user`` — the role
    is re-read from the DB on every request (not cached in the JWT), so a
    role change takes effect on a user's next call, not their next login."""

    async def checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
        return current_user

    return checker
