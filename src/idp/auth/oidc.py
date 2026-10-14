"""Sign-in through the corporate identity provider (VRT-57): OpenID Connect
authorization code with PKCE, Veritium as a confidential client. Any
provider that speaks OIDC works (Entra ID, Okta, Keycloak); development uses
Keycloak (deploy/keycloak).

A person's business units and roles come from the provider's groups, named
"<prefix>:<unit>:<role>" (veritium:pymes:operador). At each sign-in they
replace the person's memberships that came from the provider; a group naming
an unregistered unit or an unknown role grants nothing, and memberships
managed in Veritium are left alone. Removing someone there takes effect at
their next sign-in, or when their token expires."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.config import Settings
from idp.persistence.models import Membership, Tenant, User
from idp.persistence.repositories import UserRepository

ROLES = {"admin", "operador", "visor", "especialista_ia"}
_LEEWAY_SECONDS = 30


class SignInFailed(Exception):
    """Why a sign-in through the provider did not go through (logged, never shown in detail)."""


@dataclass(frozen=True)
class Attempt:
    """What the sign-in started with, kept by the browser (signed) until the provider sends it back."""

    state: str
    nonce: str
    verifier: str
    tenant: str | None


def start(tenant: str | None) -> Attempt:
    return Attempt(state=secrets.token_urlsafe(24), nonce=secrets.token_urlsafe(24), verifier=secrets.token_urlsafe(48), tenant=tenant)


def seal(settings: Settings, attempt: Attempt) -> str:
    return jwt.encode({"st": attempt.state, "no": attempt.nonce, "pv": attempt.verifier, "ten": attempt.tenant}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def unseal(settings: Settings, sealed: str) -> Attempt:
    try:
        c = jwt.decode(sealed, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise SignInFailed("el intento de ingreso no es válido") from exc
    return Attempt(state=c["st"], nonce=c["no"], verifier=c["pv"], tenant=c.get("ten"))


def callback_url(settings: Settings) -> str:
    return f"{settings.public_api_base_url.rstrip('/')}/auth/oidc/callback"


async def _discover(settings: Settings, client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get(f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration")  # type: ignore[union-attr]
    response.raise_for_status()
    return response.json()


async def authorization_url(settings: Settings, attempt: Attempt) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        endpoint = (await _discover(settings, client))["authorization_endpoint"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).rstrip(b"=").decode()
    query = {
        "response_type": "code", "client_id": settings.oidc_client_id, "redirect_uri": callback_url(settings), "scope": "openid email profile",
        "state": attempt.state, "nonce": attempt.nonce, "code_challenge": challenge, "code_challenge_method": "S256",
    }
    return f"{endpoint}?{urlencode(query)}"


async def identity(settings: Settings, attempt: Attempt, *, code: str, state: str) -> dict[str, Any]:
    """The verified claims of the person the provider sent back."""
    if not secrets.compare_digest(state, attempt.state):
        raise SignInFailed("el estado no coincide")
    secret = settings.oidc_client_secret.get_secret_value() if settings.oidc_client_secret else ""
    async with httpx.AsyncClient(timeout=10) as client:
        provider = await _discover(settings, client)
        tokens = await client.post(
            provider["token_endpoint"],
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": callback_url(settings), "code_verifier": attempt.verifier},
            auth=(settings.oidc_client_id, secret),
        )
        if tokens.status_code != 200:
            raise SignInFailed(f"el proveedor rechazó el código ({tokens.status_code})")
        keys = (await client.get(provider["jwks_uri"])).json()
    body = tokens.json()
    try:
        claims = jwt.decode(
            body["id_token"], keys, algorithms=provider.get("id_token_signing_alg_values_supported", ["RS256"]),
            audience=settings.oidc_client_id, issuer=provider["issuer"], access_token=body.get("access_token"), options={"leeway": _LEEWAY_SECONDS},
        )
    except (JWTError, KeyError) as exc:
        raise SignInFailed(f"id_token inválido: {exc}") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), attempt.nonce):
        raise SignInFailed("el nonce no coincide")
    return claims


def units_from(settings: Settings, claims: dict[str, Any]) -> dict[str, str]:
    """{unit: role} from the provider's groups; with two roles in one unit, the broader one."""
    rank = ["visor", "operador", "especialista_ia", "admin"]
    found: dict[str, str] = {}
    groups = claims.get(settings.oidc_groups_claim) or []
    for group in groups if isinstance(groups, list) else []:
        prefix, _, rest = str(group).lstrip("/").partition(":")
        unit, _, role = rest.partition(":")
        if prefix == settings.oidc_group_prefix and role in ROLES and (unit not in found or rank.index(role) > rank.index(found[unit])):
            found[unit] = role
    return found


async def sign_in(settings: Settings, session: AsyncSession, claims: dict[str, Any]) -> User:
    """The person behind the claims, created the first time, with their memberships from the groups."""
    subject = f"{claims['iss']} {claims['sub']}"
    users = UserRepository(session)
    user = await session.scalar(select(User).where(User.subject == subject))
    email = str(claims.get("email") or "")
    if user is None and email:
        user = await users.get_by_email(email)
        if user is not None:
            if user.subject is not None or claims.get("email_verified") is not True:
                raise SignInFailed("ese correo ya pertenece a otra cuenta")
            user.subject = subject  # someone who had a local account: the same person, now from the provider
    if user is None:
        if not email:
            raise SignInFailed("el proveedor no envía el correo")
        user = User(name=str(claims.get("name") or email), email=email, password_hash=None, subject=subject)
        session.add(user)
        await session.flush()
    registered = set(await session.scalars(select(Tenant.key)))
    granted = {unit: role for unit, role in units_from(settings, claims).items() if unit in registered}
    local = set(await session.scalars(select(Membership.tenant).where(Membership.user_id == user.id, Membership.source == "local")))
    await session.execute(delete(Membership).where(Membership.user_id == user.id, Membership.source == "idp"))
    for unit, role in granted.items():
        if unit not in local:  # one managed in Veritium stays as it is
            session.add(Membership(user_id=user.id, tenant=unit, role=role, source="idp"))
    await session.flush()
    return user
