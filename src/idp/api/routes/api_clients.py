"""Connected systems (VRT-65) — admin only.

GET  /v1/api-clients               list
POST /v1/api-clients               register a system → client_id + secret (shown once)
POST /v1/api-clients/{id}/rotate   new secret (shown once); tokens issued before stop working
POST /v1/api-clients/{id}/revoke   the system can no longer call, at once

A system then gets its token with ``POST /auth/token`` (client credentials)
and calls the API with role ``integracion``."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_db_session, require_role
from idp.auth.security import hash_client_secret, hash_password
from idp.config import Settings
from idp.persistence.models import ApiClient, User
from idp.persistence.repositories import UserRepository

router = APIRouter(prefix="/v1/api-clients", tags=["api-clients"])


class ApiClientView(BaseModel):
    id: uuid.UUID
    name: str
    client_id: str
    rate_limit_per_minute: int
    created_by: str
    created_at: datetime
    secret_rotated_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiClientWithSecret(ApiClientView):
    # Shown only in the response that creates or rotates it; Veritium keeps only its hash.
    client_secret: str


class ApiClientRequest(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)


def _view(client: ApiClient, settings: Settings) -> ApiClientView:
    return ApiClientView(
        id=client.id, name=client.name, client_id=client.client_id, rate_limit_per_minute=client.rate_limit_per_minute or settings.api_client_rate_limit_per_minute,
        created_by=client.created_by, created_at=client.created_at, secret_rotated_at=client.secret_rotated_at, last_used_at=client.last_used_at,
        revoked_at=client.revoked_at,
    )


async def _client_or_404(session: AsyncSession, client_id: uuid.UUID) -> ApiClient:
    client = await session.get(ApiClient, client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api client not found")
    return client


@router.get("", response_model=list[ApiClientView])
async def list_clients(
    _: User = Depends(require_role("admin")), session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_app_settings)
) -> list[ApiClientView]:
    return [_view(c, settings) for c in (await session.scalars(select(ApiClient).order_by(ApiClient.created_at))).all()]


@router.post("", response_model=ApiClientWithSecret, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ApiClientRequest,
    admin: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> ApiClientWithSecret:
    client_id, secret = f"vrt_{secrets.token_hex(8)}", secrets.token_urlsafe(32)
    # The system acts through its own user, which cannot log in with a password.
    user = await UserRepository(session).create(
        name=f"Sistema · {body.name}", email=f"{client_id}@sistemas.veritium", password_hash=hash_password(secrets.token_urlsafe(32)), role="integracion"
    )
    client = ApiClient(
        name=body.name, client_id=client_id, secret_hash=hash_client_secret(secret), user_id=user.id, rate_limit_per_minute=body.rate_limit_per_minute,
        created_by=admin.name, secret_rotated_at=datetime.now(UTC),
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return ApiClientWithSecret(**_view(client, settings).model_dump(), client_secret=secret)


@router.post("/{client_id}/rotate", response_model=ApiClientWithSecret)
async def rotate_secret(
    client_id: uuid.UUID,
    _: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> ApiClientWithSecret:
    client = await _client_or_404(session, client_id)
    if client.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="el sistema está revocado; registra uno nuevo")
    secret = secrets.token_urlsafe(32)
    client.secret_hash, client.secret_rotated_at = hash_client_secret(secret), datetime.now(UTC)
    await session.commit()
    return ApiClientWithSecret(**_view(client, settings).model_dump(), client_secret=secret)


@router.post("/{client_id}/revoke", response_model=ApiClientView)
async def revoke(
    client_id: uuid.UUID,
    admin: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> ApiClientView:
    client = await _client_or_404(session, client_id)
    if client.revoked_at is None:
        client.revoked_at, client.revoked_by = datetime.now(UTC), admin.name
        await session.commit()
    return _view(client, settings)
