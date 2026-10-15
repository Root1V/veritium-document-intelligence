"""Telemetry through argus (VRT-31): traces, metrics and logs over OTLP to
argus's collector, with its two-level identity — namespace ``veritium``, one
service per deployable process (``veritium-api``, ``veritium-worker``).

``setup_telemetry`` is the one place that configures it; everything else uses
the global tracer, so spans made here and by the auto-instrumentations
(FastAPI, httpx, SQLAlchemy, asyncpg) and Temporal's interceptor join up.
Disabled with ``ARGUS_DISABLED=1`` (the test suite sets it: an ``init`` call
exports for real, endpoint or not).

What Veritium adds on top:
- a span per case step (start, document, evaluation) with the case, run and
  document ids — what a case's cost and failures are grouped by;
- a GenAI span per model call (llm/port.py), with provider, operation, model
  and tokens; the ``traced_*`` helpers below name what a call was for.

A case run is one trace, API → aeon → Temporal → worker. Its cost, in
argus's store (``make query`` in the argus repo):

    WITH casos AS (SELECT DISTINCT TraceId, SpanAttributes['idp.case_id'] case_id
                   FROM otel.otel_traces WHERE SpanAttributes['idp.case_id'] != '')
    SELECT c.case_id, count() llamadas,
           sum(toUInt64OrZero(t.SpanAttributes['gen_ai.usage.input_tokens'])) entrada,
           sum(toUInt64OrZero(t.SpanAttributes['gen_ai.usage.output_tokens'])) salida
    FROM otel.otel_traces t INNER JOIN casos c ON c.TraceId = t.TraceId
    WHERE t.SpanAttributes['gen_ai.provider.name'] != '' GROUP BY c.case_id
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from importlib.metadata import version
from typing import Any, Literal, ParamSpec, TypeVar

import argus
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from idp.config import Settings
from idp.observability import scrub

P = ParamSpec("P")
R = TypeVar("R")

NAMESPACE = "veritium"
# The model calls go to prometheus's gateway: the provider is the system answering, not the engine behind it.
PROVIDER = "prometheus-gateway"


# deployment.environment.name is a closed set in OpenTelemetry, and argus enforces it.
_ENVIRONMENT = {"dev": "development", "test": "test", "prod": "production"}


def setup_telemetry(settings: Settings, *, component: Literal["api", "worker"]) -> None:
    """Idempotent. The API calls it in its lifespan (after uvicorn configured logging); the worker before its own."""
    scrub.install()  # no personal data in what leaves the process (VRT-58)
    if settings.environment == "prod" and argus.capture_enabled():
        raise RuntimeError("ARGUS_CAPTURE_CONTENT exporta prompts con datos personales: no se permite en producción (VRT-58)")
    argus.init(
        f"{NAMESPACE}-{component}", namespace=NAMESPACE, role=component, version=version("idp"),
        environment=_ENVIRONMENT[settings.environment], json_logs=False,
    )


def get_tracer(name: str = "idp") -> trace.Tracer:
    return trace.get_tracer(name)


def case_step(name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """A span around one step of a case run — ``(settings, case_id, run_id[, document_id])`` —
    the same whether aeon's worker or the in-process executor runs it."""

    def wrap(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def run(*args: P.args, **kwargs: P.kwargs) -> R:
            ids = [a for a in args if isinstance(a, uuid.UUID)]
            fields = dict(zip(("idp.case_id", "idp.run_id", "idp.document_id"), map(str, ids)))
            with argus.step(name, **fields):
                return await fn(*args, **kwargs)

        return run

    return wrap


@contextmanager
def model_call(request: Any) -> Iterator[argus.GenAISpan]:
    """The GenAI span of one model call (llm/port.py); the caller records the response on it."""
    with argus.genai("chat", provider=PROVIDER, request_model=request.model) as span:
        span.request_params(temperature=request.temperature, max_tokens=request.max_output_tokens, top_p=request.top_p)
        yield span


@contextmanager
def traced_stage(stage_name: str, *, document_id: str | None = None, case_id: str | None = None, **attrs: Any) -> Iterator[Span]:
    """One span per pipeline stage (parse/classify/extract/validate/review)."""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"pipeline.stage.{stage_name}") as span:
        if document_id:
            span.set_attribute("idp.document_id", document_id)
        if case_id:
            span.set_attribute("idp.case_id", case_id)
        for k, v in attrs.items():
            span.set_attribute(f"idp.{k}", v)
        try:
            yield span
        except Exception as exc:  # re-raised, span just records it
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextmanager
def traced_llm_call(*, role: str, model: str) -> Iterator[Span]:
    """What a group of model calls is for (classify, extract, a lens...). The calls
    themselves are the GenAI spans inside it (``model_call``): one fact, one span."""
    tracer = get_tracer()
    with tracer.start_as_current_span("idp.llm") as span:
        span.set_attribute("idp.llm_role", role)
        span.set_attribute("idp.llm_model", model)
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextmanager
def traced_tool_call(*, tool_name: str, turn: int | None = None, arguments: dict[str, Any] | None = None) -> Iterator[Span]:
    """One span per tool call inside the bounded agentic extraction loop.
    synaptum leaves tool execution spans to whoever executes the tool — in
    the autonomous route, these functions."""
    tracer = get_tracer()
    with tracer.start_as_current_span("gen_ai.tool") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool_name)
        if turn is not None:
            span.set_attribute("idp.agent.turn", turn)
        if arguments:
            span.set_attribute("idp.agent.arguments", str(arguments))
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextmanager
def traced_validation_rule(*, rule_id: str, category: str) -> Iterator[Span]:
    """One span per ValidationRule.evaluate() call."""
    tracer = get_tracer()
    with tracer.start_as_current_span("validation.rule") as span:
        span.set_attribute("idp.validation.rule_id", rule_id)
        span.set_attribute("idp.validation.category", category)
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
