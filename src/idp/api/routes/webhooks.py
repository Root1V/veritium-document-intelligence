"""Webhook endpoints (VRT-28) — how a calling process learns about a case
without polling.

POST   /v1/webhook-endpoints                    register (admin) — returns the signing secret ONCE
GET    /v1/webhook-endpoints                    list (admin)
DELETE /v1/webhook-endpoints/{id}               disable (admin) — kept with its history
GET    /v1/webhook-endpoints/{id}/deliveries    recent deliveries and their state (admin)
POST   /v1/webhook-endpoints/{id}/test          send a test event to this endpoint only (admin)

Deliveries follow the Standard Webhooks spec (webhook-id / -timestamp /
-signature) with a CloudEvents 1.0 body; see scripts/webhook_sink.py for a
receiver that verifies them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_db_session, require_role
from idp.config import Settings
from idp.persistence.models import OutboxEvent, User, WebhookDelivery, WebhookEndpoint
from idp.persistence.repositories import WebhookDeliveryRepository, WebhookEndpointRepository
from idp.webhooks.cipher import MissingEncryptionKey, encrypt
from idp.webhooks.events import EVENT_TYPES, WEBHOOK_TEST
from idp.webhooks.signing import generate_secret

router = APIRouter(prefix="/v1/webhook-endpoints", tags=["webhooks"], dependencies=[Depends(require_role("admin"))])

_TENANT = "default"  # multi-tenant arrives with VRT-57


class CreateEndpointRequest(BaseModel):
    url: AnyHttpUrl
    event_types: list[str] = Field(default_factory=list, description="Tipos a recibir; vacío = todos.")
    description: str | None = None

    @field_validator("event_types")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(EVENT_TYPES))
        if unknown:
            raise ValueError(f"tipos de evento desconocidos: {unknown}; válidos: {list(EVENT_TYPES)}")
        return value


class EndpointResponse(BaseModel):
    id: uuid.UUID
    url: str
    description: str | None
    event_types: list[str]
    active: bool
    created_by: str | None
    created_at: datetime
    disabled_at: datetime | None


class CreatedEndpointResponse(EndpointResponse):
    secret: str = Field(description="Secreto de firma (whsec_…). Se muestra solo esta vez.")


class DeliveryResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    subject: str | None
    status: str
    attempts: int
    next_attempt_at: datetime
    last_status_code: int | None
    last_error: str | None
    last_latency_ms: int | None
    delivered_at: datetime | None


def _endpoint(e: WebhookEndpoint) -> EndpointResponse:
    return EndpointResponse(
        id=e.id, url=e.url, description=e.description, event_types=e.event_types, active=e.active,
        created_by=e.created_by, created_at=e.created_at, disabled_at=e.disabled_at,
    )


async def _endpoint_or_404(session: AsyncSession, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    endpoint = await WebhookEndpointRepository(session).get(endpoint_id)
    if endpoint is None or endpoint.tenant != _TENANT:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="webhook endpoint not found")
    return endpoint


@router.post("", response_model=CreatedEndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    body: CreateEndpointRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(require_role("admin")),
) -> CreatedEndpointResponse:
    secret = generate_secret()
    try:
        ciphertext = encrypt(settings, secret)
    except MissingEncryptionKey as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    endpoint = await WebhookEndpointRepository(session).create(
        WebhookEndpoint(tenant=_TENANT, url=str(body.url), description=body.description, event_types=body.event_types, secret_ciphertext=ciphertext, created_by=user.email)
    )
    await session.commit()
    await session.refresh(endpoint)
    return CreatedEndpointResponse(**_endpoint(endpoint).model_dump(), secret=secret)


@router.get("", response_model=list[EndpointResponse])
async def list_endpoints(session: AsyncSession = Depends(get_db_session)) -> list[EndpointResponse]:
    return [_endpoint(e) for e in await WebhookEndpointRepository(session).list(tenant=_TENANT)]


@router.delete("/{endpoint_id}", response_model=EndpointResponse)
async def disable_endpoint(endpoint_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> EndpointResponse:
    endpoint = await _endpoint_or_404(session, endpoint_id)
    if endpoint.active:
        await WebhookEndpointRepository(session).disable(endpoint)
        await session.commit()
    return _endpoint(endpoint)


@router.get("/{endpoint_id}/deliveries", response_model=list[DeliveryResponse])
async def list_deliveries(endpoint_id: uuid.UUID, limit: int = 50, session: AsyncSession = Depends(get_db_session)) -> list[DeliveryResponse]:
    await _endpoint_or_404(session, endpoint_id)
    return [
        DeliveryResponse(
            id=d.id, event_id=d.event_id, event_type=d.event.type, subject=d.event.subject, status=d.status, attempts=d.attempts,
            next_attempt_at=d.next_attempt_at, last_status_code=d.last_status_code, last_error=d.last_error,
            last_latency_ms=d.last_latency_ms, delivered_at=d.delivered_at,
        )
        for d in await WebhookDeliveryRepository(session).list_for_endpoint(endpoint_id, limit=min(limit, 200))
    ]


@router.post("/{endpoint_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def send_test_event(endpoint_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict[str, str]:
    """A test event delivered to this endpoint only: created already
    dispatched, with its single delivery, so the fan-out never sends it to
    other endpoints."""
    endpoint = await _endpoint_or_404(session, endpoint_id)
    if not endpoint.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="endpoint desactivado")
    event = OutboxEvent(tenant=_TENANT, type=WEBHOOK_TEST, subject=str(endpoint.id), data={"message": "Evento de prueba de Veritium"}, dispatched_at=datetime.now(UTC))
    session.add(event)
    await session.flush()
    session.add(WebhookDelivery(event_id=event.id, endpoint_id=endpoint.id))
    await session.commit()
    return {"event_id": str(event.id), "status": "queued"}
