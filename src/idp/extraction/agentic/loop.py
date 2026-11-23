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

The document's own rules run on the submission itself (VRT-113): the agent
was told to check its draft, and often did not.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel
from synaptum import LimitExceeded, NoObjectGeneratedError, Text, ToolStep
from synaptum.schema.protocol import PydanticSchema

from idp.config import Settings
from idp.domain.envelope import ToolCallRecord
from idp.extraction.agentic.prompts import build_system_prompt
from idp.extraction.agentic.tools import draft_tool, region_tools
from idp.extraction.self_check import DraftChecker
from idp.llm.port import inference, model_for
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument


class ExtractionIncomplete(Exception):
    """Raised when the agent ends without a valid submission — it never
    submitted within ``extraction_max_turns`` (``LimitExceeded``) or never
    submitted a valid one (``NoObjectGeneratedError``). Callers mark the
    document ``needs_review`` rather than failing the whole pipeline."""


class _CheckedOnSubmit(PydanticSchema):
    """The target schema, plus the document's own rules on the first valid
    submission: what they find goes back to the agent once, to look again —
    the OCR may have lost or misread a value. The next submission is
    accepted as it comes: if the document really says so, validation
    reports it as always."""

    def __init__(self, target: type[BaseModel], checker: DraftChecker) -> None:
        super().__init__(target)
        self._checker, self._checked = checker, False

    def validate(self, data: Any) -> Any:
        result = super().validate(data)
        if self._checked:
            return result
        self._checked = True
        draft = {k: v for k, v in result.model_dump().items() if k != "unreadable_fields"}
        # The rules are computations, no I/O: run to completion off this loop, which is the agent's.
        with ThreadPoolExecutor(max_workers=1) as pool:
            problems = pool.submit(asyncio.run, self._checker.check(draft)).result()
        if problems:
            raise NoObjectGeneratedError(
                "the document's own rules found problems in this draft:\n" + "\n".join(f"- {p}" for p in problems) + "\n"
                "Look at those fields again: re-read their regions, or use look_closer on their labels — the OCR may have lost or "
                "misread a value. If one cannot be read, list it in unreadable_fields. If the document really says so, submit the "
                "same again: it will be accepted.",
                raw=repr(data),
            )
        return result


def _record(turn: int, step: ToolStep) -> ToolCallRecord:
    content = step.result.content if step.result is not None else ()
    summary = " ".join(p.text for p in content if isinstance(p, Text))
    return ToolCallRecord(turn=turn, tool_name=step.call.name, arguments=dict(step.call.arguments), result_summary=summary[:500])


def run_agentic_extraction(
    settings: Settings,
    parsed: ParsedDocument,
    schema_cls: type[BaseModel],
    *,
    purpose: str,
    hint: str,
    correction_note: str | None = None,
    grounding: dict[str, str] | None = None,
    checker: DraftChecker | None = None,
) -> tuple[BaseModel, list[ToolCallRecord]]:
    task = "Extrae los datos del documento segun el esquema objetivo."
    if correction_note:
        task += f"\n\nCorreccion requerida: {correction_note}"
    port = inference()
    with traced_llm_call(role="reasoning", model=model_for("reasoning")):
        try:
            result, steps = port.run_sync(
                port.run_agent(
                    purpose=purpose,
                    instructions=build_system_prompt(hint, schema_cls, parsed, grounding, self_check=checker is not None and checker.tool),
                    task=task,
                    tools=region_tools(parsed) + ([draft_tool(checker)] if checker is not None and checker.tool else []),
                    output=_CheckedOnSubmit(schema_cls, checker) if checker is not None else schema_cls,  # type: ignore[arg-type]
                    max_steps=settings.extraction_max_turns,
                )
            )
        except (LimitExceeded, NoObjectGeneratedError) as exc:
            raise ExtractionIncomplete(f"{type(exc).__name__}: {exc}") from exc
    return result, [_record(turn, step) for turn, step in enumerate(steps, start=1)]
