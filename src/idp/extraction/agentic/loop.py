"""The bounded ReAct extraction loop (VRT-30): a synaptum ``Agent`` with a
fixed toolset (tools.py), a fixed target schema delivered through
synaptum's submit tool, and a hard turn cap. This is the resolved answer to
"the target schema is stable but the layout isn't" — the *what* stays
fixed, the *how*/*where* is delegated to the model.

synaptum runs the loop: a submission that does not validate is returned
with its error (each correction costs a turn), a tool called with the wrong
arguments is an error the model can recover from, and every step is
journaled. Each tool call is recorded into ``ToolCallRecord``s so the extra
flexibility versus a single fixed prompt does not cost auditability.
"""

from __future__ import annotations

from pydantic import BaseModel
from synaptum import LimitExceeded, NoObjectGeneratedError, Text, ToolStep

from idp.config import Settings
from idp.domain.document_types import DocumentType
from idp.domain.envelope import ToolCallRecord
from idp.extraction.agentic.prompts import build_system_prompt
from idp.extraction.agentic.tools import region_tools
from idp.llm.port import inference
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument


class ExtractionIncomplete(Exception):
    """Raised when the agent ends without a valid submission — it never
    submitted within ``extraction_max_turns`` (``LimitExceeded``) or never
    submitted a valid one (``NoObjectGeneratedError``). Callers mark the
    document ``needs_review`` rather than failing the whole pipeline."""


def _record(turn: int, step: ToolStep) -> ToolCallRecord:
    content = step.result.content if step.result is not None else ()
    summary = " ".join(p.text for p in content if isinstance(p, Text))
    return ToolCallRecord(turn=turn, tool_name=step.call.name, arguments=dict(step.call.arguments), result_summary=summary[:500])


def run_agentic_extraction(
    settings: Settings,
    parsed: ParsedDocument,
    schema_cls: type[BaseModel],
    document_type: DocumentType,
    correction_note: str | None = None,
) -> tuple[BaseModel, list[ToolCallRecord]]:
    task = "Extrae los datos del documento segun el esquema objetivo."
    if correction_note:
        task += f"\n\nCorreccion requerida: {correction_note}"
    port = inference()
    with traced_llm_call(role="reasoning", model=settings.reasoning_model):
        try:
            result, steps = port.run_sync(
                port.run_agent(
                    purpose=f"extract/{document_type.value}",
                    instructions=build_system_prompt(document_type, schema_cls, parsed),
                    task=task,
                    tools=region_tools(parsed),
                    output=schema_cls,
                    max_steps=settings.extraction_max_turns,
                )
            )
        except (LimitExceeded, NoObjectGeneratedError) as exc:
            raise ExtractionIncomplete(f"{type(exc).__name__}: {exc}") from exc
    return result, [_record(turn, step) for turn, step in enumerate(steps, start=1)]
