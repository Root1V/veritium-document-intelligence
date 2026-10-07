"""OpenTelemetry instrumentation layer. This is Phase 0's instrumentation
mechanism from day one, not a Phase 1+ addition — only the exporter (console
locally, an OTEL Collector -> Langfuse/whatever backend later) changes
between phases; call sites using ``traced_*`` never change.

Instruments: pipeline stages, LLM/VLM calls (GenAI semantic conventions),
tool calls inside the bounded agentic extraction loop, and validation rule
evaluations.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.trace import Span, Status, StatusCode

from idp.config import Settings

_configured = False


def setup_tracing(settings: Settings) -> None:
    """Idempotent: safe to call multiple times (e.g. once per test)."""
    global _configured
    if _configured:
        return
    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    if settings.otel_console_export:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str = "idp") -> trace.Tracer:
    return trace.get_tracer(name)


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
def traced_llm_call(*, role: str, model: str, system: str = "openai-compatible") -> Iterator[Span]:
    """One span per LLM/VLM call, following OTEL GenAI semantic conventions."""
    tracer = get_tracer()
    with tracer.start_as_current_span("gen_ai.chat") as span:
        span.set_attribute("gen_ai.system", system)
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("idp.llm_role", role)
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


def record_llm_usage(span: Span, *, input_tokens: int | None, output_tokens: int | None) -> None:
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)


@contextmanager
def traced_tool_call(*, tool_name: str, turn: int, arguments: dict[str, Any] | None = None) -> Iterator[Span]:
    """One span per tool call inside the bounded agentic extraction loop."""
    tracer = get_tracer()
    with tracer.start_as_current_span("gen_ai.tool") as span:
        span.set_attribute("gen_ai.tool.name", tool_name)
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
