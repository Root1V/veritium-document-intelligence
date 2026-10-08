"""Unit tests for VRT-26: the graph a case run becomes on aeon, its
agreement with aeon's graph schema and with Veritium's Cedar bundle, and
the worker's error mapping. No DB, no network."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import jsonschema
import pytest
import yaml
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from idp.config import Settings
from idp.execution.aeon import ACTIVITY_NAMES, EVALUATE, LANE_QUEUES, PROCESS_DOCUMENT, START_RUN, build_case_graph, task_queue_for
from idp.worker import activities

ROOT = Path(__file__).resolve().parents[2]
AEON_SCHEMA = ROOT.parent / "aeon-ai" / "proto" / "schemas" / "graph_spec.schema.json"
CASE, RUN = uuid.uuid4(), uuid.uuid4()


def _graph(n: int, queue: str = "veritium-online") -> dict:
    return build_case_graph(case_id=CASE, run_id=RUN, document_ids=[uuid.uuid4() for _ in range(n)], task_queue=queue)


def test_graph_is_start_then_documents_in_parallel_then_evaluate():
    graph = _graph(3)
    start, documents, evaluate = graph["children"]
    assert graph["kind"] == "sequential"
    assert (start["activity_name"], evaluate["activity_name"]) == (START_RUN, EVALUATE)
    assert documents["kind"] == "parallel" and len(documents["children"]) == 3
    assert all(d["activity_name"] == PROCESS_DOCUMENT and d["heartbeat_seconds"] for d in documents["children"])
    assert len({d["args"]["document_id"] for d in documents["children"]}) == 3
    # Steps carry ids only; every node runs on the lane's queue.
    assert start["args"] == {"case_id": str(CASE), "run_id": str(RUN)}
    leaves = [start, evaluate, *documents["children"]]
    assert {n["task_queue"] for n in leaves} == {"veritium-online"}


def test_a_run_with_nothing_to_extract_has_no_parallel_node():
    assert [c["id"] for c in _graph(0)["children"]] == ["start", "evaluate"]


def test_lanes_map_to_queues_and_unknown_channels_fall_back_to_backoffice():
    assert task_queue_for("online") == "veritium-online"
    assert task_queue_for("bulk") == "veritium-bulk"
    assert task_queue_for("fax") == "veritium-backoffice"


@pytest.mark.skipif(not AEON_SCHEMA.exists(), reason="aeon checkout not found next to this repo")
def test_graph_validates_against_aeons_schema():
    schema = json.loads(AEON_SCHEMA.read_text())
    for n in (0, 2):
        jsonschema.validate(_graph(n), schema)


def test_cedar_bundle_permits_exactly_our_activities_and_queues():
    bundle = yaml.safe_load((ROOT / "deploy" / "aeon" / "policy_bundle.yaml").read_text())
    source = "\n".join(p["cedarSource"] for p in bundle["policies"])
    assert "resource is ExternalActivity" in source
    for name in ACTIVITY_NAMES:
        assert f'"{name}"' in source
    for queue in LANE_QUEUES.values():
        assert f'"{queue}"' in source


@pytest.mark.asyncio
async def test_a_missing_case_is_a_non_retryable_error(monkeypatch):
    async def missing(*_):
        raise ValueError("case run not found")

    monkeypatch.setattr(activities, "start_run", missing)
    acts = activities.CaseActivities(Settings(_env_file=None))
    with pytest.raises(ApplicationError) as err:
        await ActivityEnvironment().run(acts.start_run, {"case_id": str(CASE), "run_id": str(RUN)})
    assert err.value.non_retryable and err.value.type == "CaseRunNotFound"


@pytest.mark.asyncio
async def test_process_document_heartbeats_while_it_runs(monkeypatch):
    async def slow(*_):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(activities, "process_document", slow)
    monkeypatch.setattr(activities, "DOCUMENT_HEARTBEAT_SECONDS", 0.03)
    env, beats = ActivityEnvironment(), []
    env.on_heartbeat = lambda *details: beats.append(details)
    acts = activities.CaseActivities(Settings(_env_file=None))
    await env.run(acts.process_document, {"case_id": str(CASE), "run_id": str(RUN), "document_id": str(uuid.uuid4())})
    assert len(beats) >= 2
