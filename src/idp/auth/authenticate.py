"""Who is calling, from a bearer token — one place for the REST API and the
MCP server (VRT-51): a person's login token, or a connected system's
client-credentials token (VRT-65), which must still be active and newer
than its last rotation. The quota is checked apart, by each surface, since
each answers it in its own protocol (HTTP 429 / a JSON-RPC error)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.auth.rate_limit import limiter
from idp.auth.security import decode_claims
from idp.config import Settings
from idp.persistence.models import ApiClient, User
from idp.persistence.repositories import UserRepository


class AuthFailure(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user: User
    client: ApiClient | None  # set when a connected system calls


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
        client = await session.scalar(select(ApiClient).where(ApiClient.client_id == claims["cid"]))
        if client is None or client.revoked_at is not None or client.user_id != user_id:
            raise AuthFailure
        if float(claims.get("iat", 0)) < client.secret_rotated_at.timestamp():
            raise AuthFailure
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise AuthFailure
    return Principal(user=user, client=client)


def over_quota(settings: Settings, client_id: str, rate_limit_per_minute: int | None) -> int | None:
    """Counts a call of a connected system. None if allowed, else the seconds to wait."""
    return limiter.check(client_id, rate_limit_per_minute or settings.api_client_rate_limit_per_minute)


async def touch(session: AsyncSession, client: ApiClient) -> None:
    now = datetime.now(UTC)
    if client.last_used_at is None or now - client.last_used_at > timedelta(minutes=1):  # not one write per call
        client.last_used_at = now
        await session.commit()
