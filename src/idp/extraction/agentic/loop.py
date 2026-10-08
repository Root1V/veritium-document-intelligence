"""The bounded ReAct extraction loop itself: fixed toolset (tools.py), fixed
target schema, hard turn cap, one bounded self-correction turn on schema
validation failure. This is the resolved answer to "the target schema is
stable but the layout isn't" — the *what* stays fixed, the *how*/*where* is
delegated to the model.

Every turn/tool-call is OTEL-traced and recorded into ``ToolCallRecord``s so
the extra flexibility versus a single fixed prompt does not cost auditability.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from idp.config import Settings
from idp.domain.document_types import DocumentType
from idp.domain.envelope import ToolCallRecord
from idp.extraction.agentic.prompts import build_system_prompt
from idp.extraction.agentic.tools import TOOL_SPECS, dispatch_tool
from idp.llm.client import make_client
from idp.observability.otel import traced_llm_call, traced_tool_call
from idp.parsing.normalize import ParsedDocument


class ExtractionIncomplete(Exception):
    """Raised when the loop exhausts ``max_turns`` without a valid
    ``submit_extraction`` call. Callers mark the document ``needs_review``
    rather than failing the whole pipeline."""


def _submit_tool_spec(schema_cls: type[BaseModel]) -> dict[str, Any]:
    schema = schema_cls.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": "submit_extraction",
            "description": "Entrega el resultado final de la extraccion segun el esquema objetivo.",
            "parameters": schema,
        },
    }


def run_agentic_extraction(
    settings: Settings,
    parsed: ParsedDocument,
    schema_cls: type[BaseModel],
    document_type: DocumentType,
    correction_note: str | None = None,
) -> tuple[BaseModel, list[ToolCallRecord]]:
    client = make_client(settings)
    system_prompt = build_system_prompt(document_type, schema_cls, parsed)
    tools = [*TOOL_SPECS, _submit_tool_spec(schema_cls)]

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Extrae los datos del documento segun el esquema objetivo."},
    ]
    if correction_note:
        messages.append({"role": "user", "content": f"Correccion requerida: {correction_note}"})

    trace: list[ToolCallRecord] = []

    for turn in range(1, settings.extraction_max_turns + 1):
        with traced_llm_call(role="reasoning", model=settings.reasoning_model):
            response = client.chat.completions.create(
                model=settings.reasoning_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
            )
        message = response.choices[0].message

        if not message.tool_calls:
            messages.append({"role": "assistant", "content": message.content or ""})
            messages.append(
                {"role": "user", "content": "Debes usar una herramienta. Para finalizar, llama a submit_extraction."}
            )
            continue

        messages.append(message.model_dump(exclude_none=True))

        for tool_call in message.tool_calls:
            name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}

            if name == "submit_extraction":
                try:
                    result = schema_cls.model_validate(arguments)
                except ValidationError as exc:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"Error de validacion: {exc}. Corrige los campos y vuelve a llamar submit_extraction.",
                        }
                    )
                    continue
                return result, trace

            with traced_tool_call(tool_name=name, turn=turn, arguments=arguments):
                tool_result = dispatch_tool(name, arguments, parsed, settings)
            trace.append(
                ToolCallRecord(turn=turn, tool_name=name, arguments=arguments, result_summary=tool_result[:500])
            )
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_result})

    raise ExtractionIncomplete(f"agotado max_turns={settings.extraction_max_turns} sin submit_extraction valido")
