"""Webhook delivery against real Postgres and a real HTTP receiver (VRT-28):
fan-out honours subscriptions and skips disabled endpoints, deliveries are
signed per Standard Webhooks with webhook-id = event id, and a failing
endpoint is rescheduled instead of dropped."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import delete, select

from idp.persistence.db import get_session_factory
from idp.persistence.models import OutboxEvent, WebhookDelivery, WebhookEndpoint
from idp.webhooks import dispatcher
from idp.webhooks.cipher import encrypt
from idp.webhooks.events import CASE_RUN_COMPLETED, CASE_VERDICT_CHANGED
from idp.webhooks.signing import generate_secret, verify

pytestmark = [pytest.mark.usefixtures("require_postgres")]


class _Receiver:
    def __init__(self, secret: str, status: int) -> None:
        self.received: list[dict] = []
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers["content-length"]))
                receiver.received.append(
                    {
                        "id": self.headers["webhook-id"],
                        "valid": verify(secret, self.headers["webhook-id"], self.headers["webhook-timestamp"], self.headers["webhook-signature"], body),
                    }
                )
                self.send_response(status)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.mark.asyncio
async def test_fan_out_sign_deliver_and_retry(live_settings):
    settings = live_settings.model_copy(update={"secrets_encryption_key": SecretStr(Fernet.generate_key().decode())})
    good_secret, bad_secret = generate_secret(), generate_secret()
    good, failing = _Receiver(good_secret, 200), _Receiver(bad_secret, 500)
    factory = get_session_factory(settings)

    async with factory() as session:
        good_ep = WebhookEndpoint(url=good.url, event_types=[], secret_ciphertext=encrypt(settings, good_secret))
        failing_ep = WebhookEndpoint(url=failing.url, event_types=[CASE_VERDICT_CHANGED], secret_ciphertext=encrypt(settings, bad_secret))
        disabled_ep = WebhookEndpoint(url=good.url, event_types=[], secret_ciphertext=encrypt(settings, good_secret), active=False, disabled_at=datetime.now(UTC))
        run_event = OutboxEvent(type=CASE_RUN_COMPLETED, subject="test", data={"case_id": "test"})
        verdict_event = OutboxEvent(type=CASE_VERDICT_CHANGED, subject="test", data={"case_id": "test", "verdict": "continue"})
        session.add_all([good_ep, failing_ep, disabled_ep, run_event, verdict_event])
        await session.commit()
        ids = {"endpoints": [good_ep.id, failing_ep.id, disabled_ep.id], "events": [run_event.id, verdict_event.id]}

    try:
        await dispatcher.fan_out(settings)
        async with httpx.AsyncClient() as client:
            await dispatcher.deliver_due(settings, client)

        async with factory() as session:
            rows = (await session.scalars(select(WebhookDelivery).where(WebhookDelivery.event_id.in_(ids["events"])))).all()
            by = {(r.event_id, r.endpoint_id): r for r in rows}

        # Subscriptions: good gets both, failing only the verdict, disabled nothing.
        assert set(by) == {(run_event.id, good_ep.id), (verdict_event.id, good_ep.id), (verdict_event.id, failing_ep.id)}
        assert all(by[(e, good_ep.id)].status == "delivered" for e in ids["events"])
        assert sorted(r["id"] for r in good.received) == sorted(str(e) for e in ids["events"])  # webhook-id = event id
        assert all(r["valid"] for r in good.received)

        retry = by[(verdict_event.id, failing_ep.id)]
        assert retry.status == "pending" and retry.attempts == 1 and retry.last_status_code == 500
        assert retry.next_attempt_at > datetime.now(UTC)
        assert failing.received and failing.received[0]["valid"]
    finally:
        async with factory() as session:
            await session.execute(delete(OutboxEvent).where(OutboxEvent.id.in_(ids["events"])))
            await session.execute(delete(WebhookEndpoint).where(WebhookEndpoint.id.in_(ids["endpoints"])))
            await session.commit()
        good.server.shutdown()
        failing.server.shutdown()
