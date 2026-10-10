"""Explicit dependency injection via FastAPI's ``Depends`` — deliberately not
module-level singletons (the PoC's ``ocr = PaddleOCR(...)`` anti-pattern)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from idp.auth.authenticate import AuthFailure, authenticate, over_quota, touch
from idp.config import Settings, get_settings
from idp.persistence.db import get_session_factory
from idp.persistence.models import User
from idp.persistence.repositories import ReferenceDataRepository
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
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing credentials")
    try:
        principal = await authenticate(settings, session, credentials.credentials)
    except AuthFailure:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing credentials") from None
    if principal.client is not None:
        if (retry_after := over_quota(settings, principal.client.client_id, principal.client.rate_limit_per_minute)) is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="se superó la cuota de llamadas por minuto", headers={"Retry-After": str(retry_after)}
            )
        await touch(session, principal.client)
    return principal.user


def require_role(*allowed_roles: str):
    """Route-level dependency, additive to ``get_current_user`` — the role
    is re-read from the DB on every request (not cached in the JWT), so a
    role change takes effect on a user's next call, not their next login."""

    async def checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
        return current_user

    return checker
