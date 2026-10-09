"""Veritium's worker (VRT-26): ``python -m idp.worker``.

- Serves the case-run steps on one task queue per lane (veritium-online,
  -backoffice, -bulk), each with its own concurrency, against the Temporal
  of Veritium's aeon deployment.
- Reconciles: a run whose aeon run failed or was cancelled before reaching
  evaluation is marked failed (and ``run.failed`` emitted) instead of
  staying ``running`` forever — aeon does not call back."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

import httpx
from temporalio.client import Client
from temporalio.worker import Worker

from idp.config import Settings, get_settings
from idp.execution.aeon import LANE_QUEUES, run_status
from idp.llm.port import inference_lifespan
from idp.llm.prompts import current as current_prompts
from idp.llm.prompts import fingerprint, set_published
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import CaseRunRepository, PromptEditRepository, PromptRepository
from idp.pipeline.orchestrator import fail_run
from idp.worker.activities import CaseActivities

log = logging.getLogger("idp.worker")

_ENDED = {"FAILED", "CANCELLED"}


async def reconcile(settings: Settings, client: httpx.AsyncClient) -> int:
    async with get_session_factory(settings)() as session:
        runs = [(r.case_id, r.id, r.execution_ref) for r in await CaseRunRepository(session).list_unfinished_with_ref()]
    failed = 0
    for case_id, run_id, ref in runs:
        try:
            found = await run_status(settings, client, ref)
        except httpx.HTTPError as exc:
            log.warning("reconcile: aeon no respondió por %s: %s", ref, exc)
            continue
        status, failure = found if found is not None else (None, None)
        if status is None or status in _ENDED:
            reason = f"la corrida de aeon {ref} terminó en {status or 'estado desconocido (aeon no la conoce)'}"
            if failure:  # aeon's own words: the error type and message, and which step (OBS-011)
                reason += f" — {failure.get('kind', '')} {failure.get('type') or ''}: {failure.get('message', '')}".rstrip()
                if failure.get("activity"):
                    reason += f" (en {failure['activity']})"
            await fail_run(settings, case_id, run_id, reason)
            failed += 1
    return failed


async def _reconcile_loop(settings: Settings, stop: asyncio.Event) -> None:
    published_now: dict[str, str] | None = None
    async with httpx.AsyncClient() as client:
        while not stop.is_set():
            try:
                if failed := await reconcile(settings, client):
                    log.info("reconcile: %d corrida(s) marcadas como fallidas", failed)
            except Exception:
                log.exception("reconcile tick failed")
            try:
                # Prompts an AI specialist published reach the worker within a tick (VRT-63).
                async with get_session_factory(settings)() as session:
                    published = await PromptEditRepository(session).published_texts()
                if published != published_now:
                    set_published(published)
                    published_now = published
                    log.info("instrucciones publicadas en uso: %s", {name: fingerprint(text) for name, text in published.items()} or "las del código")
            except Exception:
                log.exception("prompt refresh failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_reconcile_interval_seconds)


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    activities = CaseActivities(settings).all()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with get_session_factory(settings)() as session:
        # The worker runs the prompts too: keep their text (VRT-46).
        await PromptRepository(session).record([(p.name, p.code_version, p.text) for p in current_prompts()])

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(inference_lifespan(settings))
        for lane, concurrency in settings.worker_lane_concurrency.items():
            await stack.enter_async_context(
                Worker(client, task_queue=LANE_QUEUES[lane], activities=activities, max_concurrent_activities=concurrency)
            )
            log.info("worker: %s (concurrencia %d)", LANE_QUEUES[lane], concurrency)
        await _reconcile_loop(settings, stop)
    log.info("worker detenido")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
