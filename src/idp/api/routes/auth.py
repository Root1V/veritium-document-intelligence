"""POST /auth/login — a person's login. POST /auth/token — a connected
system's token (OAuth2 client credentials, VRT-65). The only
unauthenticated routes besides /health.
No self-signup: users are created via ``scripts/create_user.py`` (internal
tool, no evidence of needing public registration)."""

from __future__ import annotations

import base64
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_db_session
from idp.auth.security import create_access_token, create_client_token, hash_client_secret, verify_password
from idp.config import Settings
from idp.persistence.models import ApiClient
from idp.persistence.repositories import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_name: str
    role: str


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> LoginResponse:
    user = await UserRepository(session).get_by_email(body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    token = create_access_token(settings, user_id=user.id)
    return LoginResponse(access_token=token, user_name=user.name, role=user.role)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


def _oauth_error(code: str, http_status: int, description: str) -> JSONResponse:
    # RFC 6749 §5.2: the error shape every OAuth2 client library understands.
    headers = {"WWW-Authenticate": "Basic"} if http_status == status.HTTP_401_UNAUTHORIZED else None
    return JSONResponse({"error": code, "error_description": description}, status_code=http_status, headers=headers)


@router.post("/token", response_model=TokenResponse, responses={400: {"description": "OAuth2 error"}, 401: {"description": "invalid_client"}})
async def token(
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse | JSONResponse:
    """OAuth2 client credentials: the id and secret in the form, or in HTTP Basic."""
    if grant_type != "client_credentials":
        return _oauth_error("unsupported_grant_type", status.HTTP_400_BAD_REQUEST, "solo se admite client_credentials")
    if authorization and authorization.lower().startswith("basic "):
        try:
            client_id, _, client_secret = base64.b64decode(authorization[6:]).decode().partition(":")
        except ValueError:
            return _oauth_error("invalid_client", status.HTTP_401_UNAUTHORIZED, "cabecera Basic inválida")
    client = await session.scalar(select(ApiClient).where(ApiClient.client_id == (client_id or "")))
    if client is None or client.revoked_at is not None or not hmac.compare_digest(client.secret_hash, hash_client_secret(client_secret or "")):
        return _oauth_error("invalid_client", status.HTTP_401_UNAUTHORIZED, "credenciales de sistema inválidas o revocadas")
    return TokenResponse(access_token=create_client_token(settings, user_id=client.user_id, client_id=client.client_id), expires_in=settings.api_client_token_minutes * 60)
