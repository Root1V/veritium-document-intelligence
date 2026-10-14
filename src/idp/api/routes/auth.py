"""How people and systems get in.

- GET /auth/oidc/login → /auth/oidc/callback: a person, through the
  corporate identity provider (VRT-57).
- POST /auth/login: a person, with a password kept here (development, a
  break-glass admin).
- Either lands in one of the person's business units; POST /auth/switch
  moves to another one; GET /auth/me says who and where.
- POST /auth/token: a connected system (OAuth2 client credentials, VRT-65).

Signing in, the token and /auth/providers are the only unauthenticated
routes besides /health. No self-signup: people come from the identity
provider, or ``scripts/create_user.py`` and the Usuarios page."""

from __future__ import annotations

import base64
import hmac
import logging
from urllib.parse import urlencode
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_db_session, get_principal
from idp.auth import oidc
from idp.auth.authenticate import Principal
from idp.auth.security import create_access_token, create_client_token, hash_client_secret, verify_password
from idp.config import Settings
from idp.persistence import tenancy
from idp.persistence.models import ApiClient, User
from idp.persistence.repositories import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    email: str
    password: str
    tenant: str | None = None  # the unit to start in; the first one otherwise


class Unit(BaseModel):
    key: str
    name: str
    role: str


class Me(BaseModel):
    user_name: str
    role: str  # in ``tenant``
    tenant: str
    tenants: list[Unit]  # every unit the person works in


class LoginResponse(Me):
    access_token: str
    token_type: str = "bearer"


async def _units(session: AsyncSession, user: User) -> list[Unit]:
    return [Unit(key=t.key, name=t.name, role=m.role) for m, t in await UserRepository(session).memberships(user.id)]


async def signed_in(settings: Settings, session: AsyncSession, user: User, tenant: str | None) -> LoginResponse:
    """A person's token for one of their units (VRT-57): ``tenant`` if they work there, else their first."""
    units = await _units(session, user)
    if not units:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no tienes ninguna unidad de negocio asignada; pídela a tu administrador")
    unit = next((u for u in units if u.key == tenant), units[0])
    token = create_access_token(settings, user_id=user.id, tenant=unit.key)
    return LoginResponse(access_token=token, user_name=user.name, role=unit.role, tenant=unit.key, tenants=units)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> LoginResponse:
    if not settings.local_login_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ingresa con tu cuenta corporativa")
    user = await UserRepository(session).get_by_email(body.email)
    if user is None or user.password_hash is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    return await signed_in(settings, session, user, body.tenant)


@router.get("/me", response_model=Me)
async def me(principal: Principal = Depends(get_principal), session: AsyncSession = Depends(get_db_session)) -> Me:
    return Me(user_name=principal.user.name, role=principal.role, tenant=principal.tenant, tenants=await _units(session, principal.user))


class SwitchRequest(BaseModel):
    tenant: str


@router.post("/switch", response_model=LoginResponse)
async def switch(
    body: SwitchRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> LoginResponse:
    """Work in another of the person's units: a new token for it."""
    if principal.client is not None or body.tenant not in {u.key for u in await _units(session, principal.user)}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no trabajas en esa unidad")
    return await signed_in(settings, session, principal.user, body.tenant)


class Providers(BaseModel):
    sso: bool  # corporate sign-in (GET /auth/oidc/login)
    local: bool  # e-mail and password (POST /auth/login)


@router.get("/providers", response_model=Providers)
async def providers(settings: Settings = Depends(get_app_settings)) -> Providers:
    """How people can sign in here, for the login page."""
    return Providers(sso=settings.oidc_issuer is not None, local=settings.local_login_enabled)


_ATTEMPT = "veritium_oidc"  # cookie: the sign-in in progress, signed, for 10 minutes


@router.get("/oidc/login", include_in_schema=False)
async def oidc_login(tenant: str | None = None, settings: Settings = Depends(get_app_settings)) -> RedirectResponse:
    """Off to the corporate identity provider; it comes back to /auth/oidc/callback."""
    if settings.oidc_issuer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no hay ingreso corporativo configurado")
    attempt = oidc.start(tenant)
    response = RedirectResponse(await oidc.authorization_url(settings, attempt), status_code=status.HTTP_302_FOUND)
    secure = settings.environment == "prod"
    response.set_cookie(_ATTEMPT, oidc.seal(settings, attempt), max_age=600, httponly=True, samesite="lax", secure=secure, path="/auth/oidc")
    return response


@router.get("/oidc/callback", include_in_schema=False)
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> RedirectResponse:
    """Back from the provider: to the login page with the token (and the
    provider's id_token, to sign out later) in the fragment — never sent to a
    server nor in a Referer — or with why not."""
    back = f"{settings.frontend_base_url.rstrip('/')}/login"

    def to(target: str) -> RedirectResponse:
        response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
        response.delete_cookie(_ATTEMPT, path="/auth/oidc")
        return response

    sealed = request.cookies.get(_ATTEMPT)
    if error or not code or not state or not sealed:
        return to(f"{back}?sso=cancelado")
    try:
        attempt = oidc.unseal(settings, sealed)
        claims, id_token = await oidc.identity(settings, attempt, code=code, state=state)
        user = await oidc.sign_in(settings, session, claims)
        await session.commit()
        signed = await signed_in(settings, session, user, attempt.tenant)
    except oidc.SignInFailed as exc:
        log.warning("ingreso corporativo rechazado: %s", exc)
        return to(f"{back}?sso=rechazado")
    except httpx.HTTPError as exc:
        log.warning("ingreso corporativo: el proveedor no respondió: %s", exc)
        return to(f"{back}?sso=proveedor")
    except HTTPException:  # signed in, but in no unit
        return to(f"{back}?sso=sin_unidades")
    return to(f"{back}#{urlencode({'token': signed.access_token, 'id_token': id_token})}")


@router.get("/oidc/logout", include_in_schema=False)
async def oidc_logout(id_token_hint: str | None = None, settings: Settings = Depends(get_app_settings)) -> RedirectResponse:
    """Out of the identity provider too, then back to the login page — so the
    next sign-in asks who it is instead of resuming the last person."""
    back = f"{settings.frontend_base_url.rstrip('/')}/login"
    if settings.oidc_issuer is None:
        return RedirectResponse(back, status_code=status.HTTP_302_FOUND)
    try:
        target = await oidc.logout_url(settings, id_token_hint)
    except httpx.HTTPError:
        target = back
    return RedirectResponse(target, status_code=status.HTTP_302_FOUND)


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
    with tenancy.system():  # the client id names the unit; there is none before it
        client = await session.scalar(select(ApiClient).where(ApiClient.client_id == (client_id or "")))
    if client is None or client.revoked_at is not None or not hmac.compare_digest(client.secret_hash, hash_client_secret(client_secret or "")):
        return _oauth_error("invalid_client", status.HTTP_401_UNAUTHORIZED, "credenciales de sistema inválidas o revocadas")
    return TokenResponse(access_token=create_client_token(settings, user_id=client.user_id, client_id=client.client_id), expires_in=settings.api_client_token_minutes * 60)


# RFC 8414 metadata lives at the root, beside the issuer — not under /auth.
well_known = APIRouter(tags=["auth"])


@well_known.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def authorization_server_metadata(settings: Settings = Depends(get_app_settings)) -> dict:
    """So an OAuth client (e.g. an MCP client, VRT-51) finds where to get tokens."""
    base = settings.public_api_base_url.rstrip("/")
    return {
        "issuer": base,
        "token_endpoint": f"{base}/auth/token",
        "grant_types_supported": ["client_credentials"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
    }
