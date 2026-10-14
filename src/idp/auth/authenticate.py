"""Who is calling, from a bearer token — one place for the REST API, MCP and
A2A (VRT-51/52): a person's login token, or a connected system's
client-credentials token (VRT-65), which must still be active and newer
than its last rotation. The quota is checked apart, by each surface, since
each answers it in its own protocol (HTTP 429 / a JSON-RPC error).

The business unit (VRT-57) comes from the credential, never from the
request: the unit a person's token was issued for, or the connected
system's own. The caller's role there is re-read on every call, and the
call then acts for that unit (persistence/tenancy.py)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.auth.rate_limit import limiter
from idp.auth.security import decode_claims
from idp.config import Settings
from idp.persistence import tenancy
from idp.persistence.models import ApiClient, User
from idp.persistence.repositories import UserRepository


class AuthFailure(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user: User
    client: ApiClient | None  # set when a connected system calls
    tenant: str
    role: str  # the caller's role in ``tenant``


async def authenticate(settings: Settings, session: AsyncSession, token: str) -> Principal:
    claims = decode_claims(settings, token)
    if claims is None or "sub" not in claims:
        raise AuthFailure
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError:
        raise AuthFailure from None
    client = None
    if "cid" in claims:
        with tenancy.system():  # a client id names its unit; it is looked up before there is one
            client = await session.scalar(select(ApiClient).where(ApiClient.client_id == claims["cid"]))
        if client is None or client.revoked_at is not None or client.user_id != user_id:
            raise AuthFailure
        if float(claims.get("iat", 0)) < client.secret_rotated_at.timestamp():
            raise AuthFailure
        tenant = client.tenant
    elif isinstance(claims.get("ten"), str) and tenancy.valid_key(claims["ten"]):
        tenant = claims["ten"]
    else:
        raise AuthFailure
    user = await UserRepository(session).get(user_id)
    role = await UserRepository(session).role_in(user_id, tenant) if user is not None else None
    if user is None or role is None:  # no longer in that unit: a new sign-in picks one they are in
        raise AuthFailure
    tenancy.use(tenant)
    return Principal(user=user, client=client, tenant=tenant, role=role)


def over_quota(settings: Settings, client_id: str, rate_limit_per_minute: int | None) -> int | None:
    """Counts a call of a connected system. None if allowed, else the seconds to wait."""
    return limiter.check(client_id, rate_limit_per_minute or settings.api_client_rate_limit_per_minute)


async def touch(session: AsyncSession, client: ApiClient) -> None:
    now = datetime.now(UTC)
    if client.last_used_at is None or now - client.last_used_at > timedelta(minutes=1):  # not one write per call
        client.last_used_at = now
        await session.commit()
