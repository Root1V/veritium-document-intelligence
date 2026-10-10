"""Veritium's A2A server (VRT-52, A2A v1.0): JSON-RPC at ``/a2a/`` and
HTTP+JSON at ``/a2a/rest``, behind the same identities as the rest of the
API; the Agent Card at ``/.well-known/agent-card.json``, signed — a JWS
(ES256) over its RFC 8785 canonical form — with the public key at
``/.well-known/jwks.json`` (the signature's ``jku``)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import add_a2a_routes_to_fastapi, create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    ClientCredentialsOAuthFlow,
    HTTPAuthSecurityScheme,
    OAuth2SecurityScheme,
    OAuthFlows,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.signing import create_agent_card_signer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from jwt.algorithms import ECAlgorithm

from idp.a2a_server.auth import CallContextBuilder, RequireAuth
from idp.a2a_server.executor import CaseAgentExecutor
from idp.a2a_server.store import PostgresTaskStore
from idp.config import Settings

log = logging.getLogger(__name__)

_INPUT = ["application/json", "application/pdf", "image/png", "image/jpeg"]
_OUTPUT = ["application/json", "text/plain"]


@dataclass(frozen=True)
class A2AServer:
    app: FastAPI  # mounted at /a2a
    card: AgentCard
    jwks: dict[str, Any]
    handler: DefaultRequestHandler


def _signing_key(settings: Settings) -> ec.EllipticCurvePrivateKey:
    if settings.a2a_signing_key is not None:
        key = serialization.load_pem_private_key(settings.a2a_signing_key.get_secret_value().encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError("A2A_SIGNING_KEY debe ser una clave EC P-256 (ES256) en PEM")
        return key
    log.warning("a2a: sin A2A_SIGNING_KEY; la Agent Card se firma con una clave efímera de este proceso (solo desarrollo)")
    return ec.generate_private_key(ec.SECP256R1())


def agent_card(settings: Settings) -> AgentCard:
    base = settings.public_api_base_url.rstrip("/")
    return AgentCard(
        name="Veritium",
        description=(
            "Decisión documental: recibe los documentos de un expediente (préstamos, convenios y otros procesos), "
            "los lee, valida y responde qué debe hacer el proceso — continuar, revisión humana o devolver al cliente — con los motivos."
        ),
        version="1.0.0",
        provider=AgentProvider(organization="Veritium", url=base),
        documentation_url=f"{base}/docs",
        # protocol_version on every interface keeps v0.3 fields out of the card.
        supported_interfaces=[
            AgentInterface(url=f"{base}/a2a/", protocol_binding="JSONRPC", protocol_version="1.0"),
            AgentInterface(url=f"{base}/a2a/rest", protocol_binding="HTTP+JSON", protocol_version="1.0"),
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        security_schemes={
            "oauth2": SecurityScheme(
                oauth2_security_scheme=OAuth2SecurityScheme(
                    description="Credenciales de sistema (client credentials), emitidas por un administrador de Veritium.",
                    flows=OAuthFlows(client_credentials=ClientCredentialsOAuthFlow(token_url=f"{base}/auth/token", scopes={})),
                )
            ),
            "bearer": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer", bearer_format="JWT")),
        },
        security_requirements=[SecurityRequirement(schemes={"oauth2": StringList(list=[])}), SecurityRequirement(schemes={"bearer": StringList(list=[])})],
        default_input_modes=_INPUT,
        default_output_modes=_OUTPUT,
        skills=[
            AgentSkill(
                id="revisar-expediente",
                name="Revisar un expediente",
                description=(
                    "Abre un expediente con una parte de datos {profile, external_ref?, process_data?} y los documentos como partes de archivo "
                    "(url autorizada o contenido). La tarea sigue la revisión y termina con el veredicto en el artefacto 'resultado'. "
                    "Si faltan documentos queda en input-required: responde en la misma tarea con ellos."
                ),
                tags=["documentos", "expediente", "validación", "crédito"],
                examples=['{"profile": "convenios", "external_ref": "EXP-1", "process_data": {"nacionalidad": "PE"}} + solicitud.pdf + boleta.pdf'],
                input_modes=_INPUT,
                output_modes=_OUTPUT,
            )
        ],
    )


def build(settings: Settings) -> A2AServer:
    key = _signing_key(settings)
    base = settings.public_api_base_url.rstrip("/")
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    sign = create_agent_card_signer(pem, {"kid": settings.a2a_signing_kid, "alg": "ES256", "jku": f"{base}/.well-known/jwks.json", "typ": "JOSE"})
    card = sign(agent_card(settings))
    jwk = ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwks = {"keys": [{**jwk, "kid": settings.a2a_signing_kid, "use": "sig", "alg": "ES256"}]}

    handler = DefaultRequestHandler(agent_executor=CaseAgentExecutor(settings), task_store=PostgresTaskStore(settings), agent_card=card)
    builder = CallContextBuilder()
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    add_a2a_routes_to_fastapi(
        app,
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/", context_builder=builder),
        rest_routes=create_rest_routes(handler, context_builder=builder, path_prefix="/rest"),
    )
    app.add_middleware(RequireAuth, settings=settings)
    return A2AServer(app=app, card=card, jwks=jwks, handler=handler)


def card_routes(server: A2AServer) -> list[Any]:
    return create_agent_card_routes(server.card)
