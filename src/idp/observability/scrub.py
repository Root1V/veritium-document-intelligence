"""No personal data in telemetry or logs (VRT-58).

Veritium's own spans carry ids and counts, never values; what can still carry
a person's data is the TEXT of an error — Postgres quotes the failing row
("DETAIL: Failing row contains (…)"), pydantic the rejected input
("input_value='KATERIN…'"), a rule its message — and every log line reaches
argus's store over OTLP. So every exception recorded on any span (Veritium's
or an auto-instrumentation's) and every log record is scrubbed here, before
it leaves the process. argus's collector redacts again, but its patterns
are not Peru's (a DNI there is 8 digits and a letter): this is the layer
that knows ours.
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import Any

from opentelemetry.sdk.trace import Span as SdkSpan

HIDDEN = "•••"
_DETAIL = re.compile(r"\n?\s*DETAIL:.*", re.DOTALL)  # Postgres quotes the row that failed
_INPUT = re.compile(r"input_value=(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|[^,\s\]]+)")  # pydantic quotes what it rejected
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# A run of 7+ digits: a DNI (8), a carné de extranjería (9-12), a RUC (11), a phone (9), an account. Not
# inside an id: a UUID's groups are bounded by hex or hyphens.
_DIGITS = re.compile(r"(?<![0-9A-Fa-f-])\d{7,}(?![0-9A-Fa-f-])")


def scrub(text: str) -> str:
    text = _DETAIL.sub("", text)
    text = _INPUT.sub(f"input_value={HIDDEN}", text)
    text = _EMAIL.sub(HIDDEN, text)
    return _DIGITS.sub(lambda m: HIDDEN + m.group(0)[-2:], text)


def _record_exception(span: SdkSpan, exception: BaseException, attributes: Any = None, timestamp: int | None = None, escaped: bool = False) -> None:
    trace_lines = "".join(traceback.format_tb(exception.__traceback__))  # where it happened, without what it said
    scrubbed = {
        "exception.message": scrub(str(exception)),
        "exception.stacktrace": f"{trace_lines}{type(exception).__qualname__}: {scrub(str(exception))}",
        **(dict(attributes) if attributes else {}),
    }
    _original_record_exception(span, exception, attributes=scrubbed, timestamp=timestamp, escaped=escaped)


def _set_status(span: SdkSpan, status: Any, description: str | None = None) -> None:
    if description:
        description = scrub(description)
    if getattr(status, "description", None):
        status = type(status)(status.status_code, scrub(status.description))
    _original_set_status(span, status, description)


_original_record_exception = SdkSpan.record_exception
_original_set_status = SdkSpan.set_status


def _arg(value: Any) -> Any:
    return scrub(value) if isinstance(value, str) else value


def _scrubbed(record: logging.LogRecord) -> logging.LogRecord:
    """The message's arguments and the exception, scrubbed — keeping the
    record's shape, which some formatters read (uvicorn's access log unpacks ``args``)."""
    if isinstance(record.msg, str):
        record.msg = scrub(record.msg)
    if isinstance(record.args, tuple):
        record.args = tuple(_arg(a) for a in record.args)
    elif isinstance(record.args, dict):
        record.args = {k: _arg(v) for k, v in record.args.items()}
    if record.exc_info and record.exc_info[1] is not None:
        exc = record.exc_info[1]
        # Where it happened and what type, with the scrubbed text; formatters print exc_text.
        record.exc_text = "".join(traceback.format_tb(exc.__traceback__)) + f"{type(exc).__qualname__}: {scrub(str(exc))}"
        record.exc_info = None
    return record


def install() -> None:
    """Idempotent: every exception any span records, and every log record created from now on, scrubbed."""
    SdkSpan.record_exception = _record_exception  # type: ignore[method-assign]
    SdkSpan.set_status = _set_status  # type: ignore[method-assign]
    factory = logging.getLogRecordFactory()
    if getattr(factory, "_veritium_scrub", False):
        return

    def scrubbing_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        return _scrubbed(factory(*args, **kwargs))

    scrubbing_factory._veritium_scrub = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(scrubbing_factory)
