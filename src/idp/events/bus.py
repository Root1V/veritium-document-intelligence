"""The event bus (VRT-49), Kafka protocol (Redpanda in development). Runs
inside the API process, like the webhook dispatcher, when
``EVENT_BUS_BROKERS`` is set.

- Relay: every outbox event is published on ``event_bus_out_topic`` in
  CloudEvents structured mode, keyed by its subject (the case), so a
  consumer reads each case's events in order. ``acks=all`` and an
  idempotent producer: a confirmed event survives a broker failover and a
  retry does not duplicate it. Marked published only after the broker
  confirms — at least once, never lost.
- Consumer: commands on ``event_bus_in_topic`` (structured or binary
  mode), handled by ``events.inbound``; the offset is committed after the
  command is answered, so a crash replays it — and the replay is answered
  the same, without doing it twice."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.structs import ConsumerRecord
from sqlalchemy import select

from idp.config import Settings
from idp.events import inbound
from idp.persistence.db import get_session_factory
from idp.persistence.models import OutboxEvent
from idp.webhooks.events import body_bytes

log = logging.getLogger(__name__)

CONTENT_TYPE = b"application/cloudevents+json; charset=UTF-8"
_BATCH = 100


def _brokers(settings: Settings) -> str:
    if not settings.event_bus_brokers:
        raise RuntimeError("EVENT_BUS_BROKERS no está configurado")
    return settings.event_bus_brokers


async def ensure_topics(settings: Settings) -> None:
    """Create the topics when missing — in development. In production they
    belong to whoever runs the bus; without permission this only logs."""
    admin = AIOKafkaAdminClient(bootstrap_servers=_brokers(settings))
    try:
        await admin.start()
        existing = set(await admin.list_topics())
        missing = [t for t in (settings.event_bus_out_topic, settings.event_bus_in_topic) if t not in existing]
        if missing:
            await admin.create_topics([NewTopic(name=t, num_partitions=3, replication_factor=1) for t in missing])
            log.info("bus: tópicos creados %s", missing)
    except Exception as exc:
        log.warning("bus: no se pudieron verificar los tópicos: %s", exc)
    finally:
        await admin.close()


async def publish_pending(settings: Settings, producer: AIOKafkaProducer) -> int:
    """Publish the outbox events not yet on the bus, oldest first. Returns how many."""
    async with get_session_factory(settings)() as session:
        stmt = select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.created_at, OutboxEvent.id).limit(_BATCH)
        events = list((await session.scalars(stmt.with_for_update(skip_locked=True))).all())
        for event in events:
            key = (event.subject or str(event.id)).encode()
            await producer.send_and_wait(settings.event_bus_out_topic, value=body_bytes(event), key=key, headers=[("content-type", CONTENT_TYPE)])
            event.published_at = datetime.now(UTC)
        await session.commit()
        return len(events)


def command_from(record: ConsumerRecord) -> dict:
    """The CloudEvent in a Kafka record, structured or binary mode (CloudEvents Kafka binding)."""
    headers = {k.lower(): (v or b"").decode() for k, v in record.headers or ()}
    if headers.get("content-type", "").startswith("application/cloudevents+json") or "ce_specversion" not in headers:
        return inbound.structured(record.value or b"")
    return inbound.binary({k.removeprefix("ce_"): v for k, v in headers.items() if k.startswith("ce_")}, record.value or b"")


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run_relay(settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        producer = AIOKafkaProducer(bootstrap_servers=_brokers(settings), acks="all", enable_idempotence=True)
        try:
            await producer.start()
            log.info("bus: publicando en %s", settings.event_bus_out_topic)
            while not stop.is_set():
                published = await publish_pending(settings, producer)
                if published:
                    log.info("bus: %d evento(s) publicados", published)
                if published < _BATCH:
                    await _sleep(stop, settings.event_bus_publish_interval_seconds)
        except Exception as exc:  # broker down: the events wait in the outbox
            log.warning("bus: el relay se reintentará: %s", exc)
            await _sleep(stop, 5.0)
        finally:
            await producer.stop()


async def run_consumer(settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        consumer = AIOKafkaConsumer(
            settings.event_bus_in_topic, bootstrap_servers=_brokers(settings), group_id=settings.event_bus_group,
            enable_auto_commit=False, auto_offset_reset="earliest",
        )
        try:
            await consumer.start()
            log.info("bus: escuchando comandos en %s", settings.event_bus_in_topic)
            while not stop.is_set():
                batches = await consumer.getmany(timeout_ms=1000)
                for records in batches.values():
                    for record in records:
                        await _consume(settings, record)
                if batches:
                    await consumer.commit()
        except Exception as exc:
            log.warning("bus: el consumidor se reintentará: %s", exc)
            await _sleep(stop, 5.0)
        finally:
            await consumer.stop()


async def _consume(settings: Settings, record: ConsumerRecord) -> None:
    try:
        command = command_from(record)
    except ValueError as exc:  # not a CloudEvent: nobody to answer, and retrying will not fix it
        log.warning("bus: mensaje descartado (offset %s): %s", record.offset, exc)
        return
    answer = await inbound.handle(settings, command)
    log.info("bus: comando %s %s → %s", command["type"], command["id"], "aceptado" if answer.accepted else f"rechazado: {answer.reason}")


async def run(settings: Settings, stop: asyncio.Event) -> None:
    await ensure_topics(settings)
    await asyncio.gather(run_relay(settings, stop), run_consumer(settings, stop))
