"""What leaves the process in telemetry and logs carries no personal data (VRT-58)."""

from __future__ import annotations

import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from idp.config import Settings
from idp.llm.port import on_premises
from idp.observability import scrub

POSTGRES = 'null value in column "tenant" violates not-null constraint\nDETAIL:  Failing row contains (b929521c, SALAS SIGUAS KATERIN, 42285866).'
PYDANTIC = "1 validation error for Payslip\nnet_pay\n  Input should be a valid number [type=float_parsing, input_value='S/ 2,500.00 KATERIN', input_type=str]"


def test_errors_lose_the_data_they_quote_and_keep_what_helps():
    assert scrub.scrub(POSTGRES) == 'null value in column "tenant" violates not-null constraint'
    assert "KATERIN" not in scrub.scrub(PYDANTIC) and "float_parsing" in scrub.scrub(PYDANTIC)
    assert scrub.scrub("DNI 42285866, correo k.salas@mail.com") == "DNI •••66, correo •••"
    assert scrub.scrub("caso 12345678-1234-1234-1234-123456789012") == "caso 12345678-1234-1234-1234-123456789012", "an id is not a datum"


def test_every_span_and_log_record_is_scrubbed():
    scrub.install()
    exporter, provider = InMemorySpanExporter(), TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with pytest.raises(ValueError), provider.get_tracer("t").start_as_current_span("db"):  # what an auto-instrumentation does
        raise ValueError(POSTGRES)
    (span,) = exporter.get_finished_spans()
    attrs = span.events[0].attributes
    assert "42285866" not in attrs["exception.message"] + attrs["exception.stacktrace"] and "KATERIN" not in attrs["exception.stacktrace"]
    assert "42285866" not in (span.status.description or "")

    record = logging.getLogger("t").makeRecord("t", logging.ERROR, __file__, 1, "falló %s", ("42285866",), (ValueError, ValueError(POSTGRES), None))
    assert "42285866" not in record.getMessage() and record.exc_info is None
    assert "42285866" not in logging.Formatter().format(record) and "ValueError" in logging.Formatter().format(record)
    access = logging.getLogger("uvicorn.access").makeRecord("a", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("1.2.3.4", "GET", "/documents?q=42285866", "1.1", 403), None)
    assert access.args[2] == "/documents?q=•••66" and len(access.args) == 5, "the shape uvicorn's formatter unpacks"


def test_in_production_the_models_must_be_ours():
    prod = Settings(_env_file=None, environment="prod", jwt_secret_key="x" * 32, a2a_signing_key="k", inference_route="governed", model_gateway_hosts=["prometheus.interno"])
    for url in ("http://127.0.0.1:8020", "http://10.0.3.7:8020", "https://prometheus.interno"):
        on_premises(prod, url)
    with pytest.raises(RuntimeError, match="no es interno"):
        on_premises(prod, "https://api.openai.com")
    on_premises(Settings(_env_file=None), "https://api.openai.com")  # development decides for itself
