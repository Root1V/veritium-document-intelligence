"""Durable executor (VRT-26): each case run is an aeon run. Veritium builds
the run's graph — start, one ``process_document`` per document in
parallel, evaluate — out of ``activity`` nodes (aeon's VRT-AEON-001) that
aeon schedules on the lane's task queue and Veritium's worker executes
(``python -m idp.worker``). aeon checks every step against Veritium's
Cedar bundle (deploy/aeon/policies/veritium.yaml) and its budgets; Temporal
makes the run survive a worker crash.

Steps only receive ids: every step reads and writes the case in Veritium's
database and is idempotent, so a retried or resumed step never duplicates
work (ADR-0003)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from fastapi import BackgroundTasks

from idp.config import Settings
from idp.pipeline.orchestrator import pending_documents

START_RUN = "veritium.case.start_run"
PROCESS_DOCUMENT = "veritium.case.process_document"
EVALUATE = "veritium.case.evaluate"
ACTIVITY_NAMES = (START_RUN, PROCESS_DOCUMENT, EVALUATE)

# One task queue per lane, so bulk work never queues ahead of online work.
LANE_QUEUES = {"online": "veritium-online", "backoffice": "veritium-backoffice", "bulk": "veritium-bulk"}

# What the worker must heartbeat within while extracting a document; the
# step itself may take up to DOCUMENT_TIMEOUT (OCR + several model calls).
DOCUMENT_HEARTBEAT_SECONDS = 30
DOCUMENT_TIMEOUT_SECONDS = 1800


def task_queue_for(channel: str) -> str:
    return LANE_QUEUES.get(channel, LANE_QUEUES["backoffice"])


def _step(node_id: str, name: str, args: dict[str, str], queue: str, *, timeout: int, heartbeat: int | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": node_id,
        "kind": "activity",
        "activity_name": name,
        "task_queue": queue,
        "args": args,
        "timeout_seconds": timeout,
        "retry": {"maximum_attempts": 3, "initial_interval_seconds": 5, "backoff": 2.0},
    }
    if heartbeat is not None:
        node["heartbeat_seconds"] = heartbeat
    return node


def build_case_graph(*, case_id: uuid.UUID, run_id: uuid.UUID, document_ids: list[uuid.UUID], task_queue: str) -> dict[str, Any]:
    ids = {"case_id": str(case_id), "run_id": str(run_id)}
    children = [_step("start", START_RUN, ids, task_queue, timeout=120)]
    if document_ids:
        children.append(
            {
                "id": "documents",
                "kind": "parallel",
                "children": [
                    _step(f"document-{d}", PROCESS_DOCUMENT, {**ids, "document_id": str(d)}, task_queue,
                          timeout=DOCUMENT_TIMEOUT_SECONDS, heartbeat=DOCUMENT_HEARTBEAT_SECONDS)
                    for d in document_ids
                ],
            }
        )
    children.append(_step("evaluate", EVALUATE, ids, task_queue, timeout=600))
    return {"id": "case-run", "kind": "sequential", "children": children}


def _headers(settings: Settings) -> dict[str, str]:
    if settings.aeon_api_token is None:
        raise RuntimeError("AEON_API_TOKEN no está configurado (scripts/aeon_dev.sh setup)")
    return {"authorization": f"Bearer {settings.aeon_api_token.get_secret_value()}"}


async def run_status(settings: Settings, client: httpx.AsyncClient, ref: str) -> str | None:
    """The aeon run's status (PENDING, RUNNING, …, FAILED, CANCELLED), or
    None when aeon does not know the run."""
    response = await client.get(f"{settings.aeon_runcontroller_url}/runs/{ref}", headers=_headers(settings), timeout=settings.aeon_request_timeout_seconds)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()["status"]


class AeonExecutor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def submit(self, *, case_id: uuid.UUID, run_id: uuid.UUID, channel: str, background: BackgroundTasks) -> str | None:
        documents = await pending_documents(self._settings, case_id)
        body = {
            "run_id": str(run_id),
            "graph": build_case_graph(case_id=case_id, run_id=run_id, document_ids=documents, task_queue=task_queue_for(channel)),
            "agent_manifest_ref": self._settings.aeon_agent_ref,
            # The manifest's activityCalls budget is not enforced from the
            # manifest yet, so the run carries it: exactly the graph's steps.
            "budgets": {"max_activity_calls": len(documents) + 2},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._settings.aeon_runcontroller_url}/runs", json=body, headers=_headers(self._settings), timeout=self._settings.aeon_request_timeout_seconds
            )
        response.raise_for_status()
        return str(run_id)
