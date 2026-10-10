"""Who calls the MCP server, and their quota (VRT-51). The same tokens as
the REST API — a person's login or a connected system's client credentials
(VRT-65), checked by the same code (auth/authenticate.py)."""

from __future__ import annotations

from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from idp.auth.authenticate import AuthFailure, authenticate, over_quota, touch
from idp.config import Settings
from idp.persistence.db import get_session_factory

# Implementation-defined JSON-RPC server error (the spec reserves -32020..-32099).
RATE_LIMITED = -32010


class VeritiumTokenVerifier:
    def __init__(self, settings: Settings, resource: str) -> None:
        self._settings, self._resource = settings, resource

    async def verify_token(self, token: str) -> AccessToken | None:
        async with get_session_factory(self._settings)() as session:
            try:
                principal = await authenticate(self._settings, session, token)
            except AuthFailure:
                return None
            client = principal.client
            if client is not None:
                await touch(session, client)
            user = principal.user
            return AccessToken(
                token=token,
                client_id=client.client_id if client else str(user.id),
                scopes=[user.role],
                subject=str(user.id),
                resource=self._resource,
                claims={
                    "name": user.name,
                    "role": user.role,
                    "api_client_id": client.client_id if client else None,
                    "rate_limit_per_minute": (client.rate_limit_per_minute if client else None),
                },
            )


def caller() -> dict[str, Any]:
    """The authenticated caller's claims (name, role, api_client_id)."""
    token = get_access_token()
    if token is None or token.claims is None:
        raise ToolError("no autenticado")
    return token.claims


def require_role(*roles: str) -> dict[str, Any]:
    claims = caller()
    if claims["role"] not in roles:
        raise ToolError(f"tu rol ({claims['role']}) no permite esta operación; se requiere {' o '.join(roles)}")
    return claims


def quota(settings: Settings):
    """Middleware: a connected system's calls count against its quota, as in the REST API."""

    async def middleware(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        token = get_access_token()
        claims = token.claims if token and token.claims else {}
        if ctx.request_id is not None and claims.get("api_client_id"):
            if (retry_after := over_quota(settings, claims["api_client_id"], claims["rate_limit_per_minute"])) is not None:
                raise MCPError(code=RATE_LIMITED, message="se superó la cuota de llamadas por minuto", data={"retryAfterSeconds": retry_after})
        return await call_next(ctx)

    return middleware
