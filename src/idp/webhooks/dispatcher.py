"""Webhook dispatcher (VRT-28). Each tick:

1. **Fan-out:** undispatched outbox events become one delivery per
   subscribed, active endpoint of the event's tenant.
2. **Delivery:** due deliveries are leased, POSTed (CloudEvents body,
   Standard Webhooks signature) and either marked delivered (2xx) or
   rescheduled with exponential backoff and jitter. After the last attempt
   (~3 days) a delivery is ``dead``.

At-least-once: a crash between sending and recording means the delivery is
sent again when its lease expires; consumers deduplicate by ``webhook-id``.
Claims use SKIP LOCKED, so several dispatchers can run side by side.

Runs inside the API process (see api/app.py lifespan), so it works with
either case executor; ``python -m idp.webhooks.dispatcher`` runs it
standalone."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from idp.config import Settings, get_settings
from idp.persistence.db import get_session_factory
from idp.persistence.models import WebhookDelivery
from idp.persistence.repositories import OutboxRepository, WebhookDeliveryRepository, WebhookEndpointRepository
from idp.webhooks.cipher import decrypt
from idp.webhooks.events import body_bytes
from idp.webhooks.signing import sign

log = logging.getLogger(__name__)

# Delay before attempt n+1 after attempt n failed: 10 attempts over ~3 days.
RETRY_DELAYS = [
    timedelta(seconds=5),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=5),
    timedelta(hours=10),
    timedelta(hours=14),
    timedelta(hours=20),
    timedelta(hours=24),
]
JITTER = 0.2
USER_AGENT = "Veritium-Webhooks/1"


def next_delay(attempts: int, *, rng: random.Random | None = None) -> timedelta | None:
    """The wait after ``attempts`` failed attempts, with ±20% jitter; None
    once the schedule is exhausted."""
    if attempts < 1 or attempts > len(RETRY_DELAYS):
        return None
    base = RETRY_DELAYS[attempts - 1].total_seconds()
    factor = 1 + (rng or random).uniform(-JITTER, JITTER)
    return timedelta(seconds=base * factor)


@dataclass
class TickStats:
    fanned_out: int = 0
    delivered: int = 0
    retried: int = 0
    dead: int = 0


async def fan_out(settings: Settings, *, tenant: str | None = None) -> int:
    async with get_session_factory(settings)() as session:
        events = await OutboxRepository(session).claim_undispatched(tenant=tenant)
        endpoints, deliveries = WebhookEndpointRepository(session), WebhookDeliveryRepository(session)
        now = datetime.now(UTC)
        for event in events:
            subscribed = await endpoints.subscribed(tenant=event.tenant, event_type=event.type)
            await deliveries.create_for(event.id, [e.id for e in subscribed])
            event.dispatched_at = now
        await session.commit()
        return len(events)


async def _send(settings: Settings, client: httpx.AsyncClient, delivery: WebhookDelivery) -> tuple[int | None, str | None, int]:
    event, endpoint = delivery.event, delivery.endpoint
    body = body_bytes(event)
    timestamp = int(time.time())
    try:
        secret = decrypt(settings, endpoint.secret_ciphertext)
    except Exception as exc:  # e.g. the encryption key was rotated: this delivery fails, the rest go on
        return None, f"no se pudo descifrar el secreto del endpoint ({type(exc).__name__})", 0
    headers = {
        "content-type": "application/json",
        "user-agent": USER_AGENT,
        "webhook-id": str(event.id),
        "webhook-timestamp": str(timestamp),
        "webhook-signature": sign(secret, str(event.id), timestamp, body),
    }
    started = time.monotonic()
    try:
        response = await client.post(endpoint.url, content=body, headers=headers, timeout=settings.webhook_request_timeout_seconds)
        return response.status_code, None if response.is_success else f"HTTP {response.status_code}", int((time.monotonic() - started) * 1000)
    except httpx.HTTPError as exc:
        return None, f"{type(exc).__name__}: {exc}"[:500], int((time.monotonic() - started) * 1000)


async def deliver_due(settings: Settings, client: httpx.AsyncClient, *, tenant: str | None = None) -> TickStats:
    stats = TickStats()
    factory = get_session_factory(settings)
    async with factory() as session:
        now = datetime.now(UTC)
        lease = now + timedelta(seconds=settings.webhook_request_timeout_seconds + 30)
        claimed = await WebhookDeliveryRepository(session).claim_due(now=now, lease_until=lease, tenant=tenant)
        await session.commit()  # the lease is taken; the HTTP calls happen outside the lock

        for delivery in claimed:
            if not delivery.endpoint.active:
                delivery.status, delivery.last_error = "dead", "endpoint desactivado"
                stats.dead += 1
                continue
            status_code, error, latency = await _send(settings, client, delivery)
            delivery.attempts += 1
            delivery.last_status_code, delivery.last_error, delivery.last_latency_ms = status_code, error, latency
            if error is None:
                delivery.status, delivery.delivered_at = "delivered", datetime.now(UTC)
                stats.delivered += 1
                continue
            delay = next_delay(delivery.attempts)
            if delay is None:
                delivery.status = "dead"
                stats.dead += 1
            else:
                delivery.next_attempt_at = datetime.now(UTC) + delay
                stats.retried += 1
        await session.commit()
    return stats


async def tick(settings: Settings, client: httpx.AsyncClient) -> TickStats:
    fanned = await fan_out(settings)
    stats = await deliver_due(settings, client)
    stats.fanned_out = fanned
    return stats


async def run(settings: Settings, stop: asyncio.Event) -> None:
    async with httpx.AsyncClient(follow_redirects=False) as client:
        while not stop.is_set():
            try:
                stats = await tick(settings, client)
                if stats.delivered or stats.retried or stats.dead:
                    log.info("webhooks: %s", stats)
            except Exception:  # never let one bad tick stop the loop
                log.exception("webhook dispatcher tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.webhook_dispatch_interval_seconds)
            except TimeoutError:
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(get_settings(), asyncio.Event()))
