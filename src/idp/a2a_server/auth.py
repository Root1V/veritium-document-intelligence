"""Who calls the A2A server (VRT-52): the same tokens, roles and quota as
the REST API and MCP (auth/authenticate.py). An ASGI middleware answers 401
or 429 at the HTTP layer — for both bindings — and leaves the principal in
the scope; the call-context builder turns it into the SDK's ``User``, whose
name is the owner of the caller's tasks."""

from __future__ import annotations

from typing import Any

from a2a.auth.user import UnauthenticatedUser, User
from a2a.server.routes import DefaultServerCallContextBuilder
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from idp.auth.authenticate import AuthFailure, Principal, authenticate, over_quota, touch
from idp.config import Settings
from idp.persistence.db import get_session_factory

PRINCIPAL = "veritium.principal"
WRITERS = ("integracion", "operador", "admin")


class VeritiumUser(User):
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        """The owner of the tasks: a system by its client id, a person by their user id."""
        client = self.principal.client
        return f"client:{client.client_id}" if client else f"user:{self.principal.user.id}"

    @property
    def role(self) -> str:
        return self.principal.user.role

    @property
    def display_name(self) -> str:
        return self.principal.user.name


class CallContextBuilder(DefaultServerCallContextBuilder):
    def build_user(self, request: Request) -> User:
        principal = request.scope.get(PRINCIPAL)
        return VeritiumUser(principal) if principal is not None else UnauthenticatedUser()


class RequireAuth:
    """401 without a valid token (with where to get one), 429 over quota."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app, self.settings = app, settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = dict(scope["headers"]).get(b"authorization", b"").decode()
        token = header[7:] if header.lower().startswith("bearer ") else None
        base = self.settings.public_api_base_url.rstrip("/")
        challenge = f'Bearer realm="veritium", authorization_uri="{base}/.well-known/oauth-authorization-server"'
        if token is None:
            await _deny(401, "faltan credenciales", {"WWW-Authenticate": challenge})(scope, receive, send)
            return
        async with get_session_factory(self.settings)() as session:
            try:
                principal = await authenticate(self.settings, session, token)
            except AuthFailure:
                await _deny(401, "credenciales inválidas o revocadas", {"WWW-Authenticate": challenge})(scope, receive, send)
                return
            if principal.client is not None:
                if (retry := over_quota(self.settings, principal.client.client_id, principal.client.rate_limit_per_minute)) is not None:
                    await _deny(429, "se superó la cuota de llamadas por minuto", {"Retry-After": str(retry)})(scope, receive, send)
                    return
                await touch(session, principal.client)
        scope[PRINCIPAL] = principal
        await self.app(scope, receive, send)


def _deny(status: int, detail: str, headers: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)
