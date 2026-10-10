"""Unit tests for VRT-30: the bounded extraction loop as a synaptum Agent
behind the InferencePort, against a scripted model (no prometheus). The
tool really reads the parsed document; the result arrives through the
submit tool, validated; failures become ExtractionIncomplete."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel
from synaptum import Request, Response, Text, ToolResult
from synaptum.testing.fake import calls, says

from idp.config import Settings
from idp.extraction.agentic.loop import ExtractionIncomplete, run_agentic_extraction
from idp.llm import port
from idp.parsing.normalize import ParsedBlock, ParsedDocument


class Boleta(BaseModel):
    empleado: str
    neto: float


PARSED = ParsedDocument(
    backend="test",
    page_count=1,
    blocks=[
        ParsedBlock(region_id=0, text="EMPLEADO: ANA PEREZ", page=0, bbox=[0, 0, 1, 0.1], confidence=0.9),
        ParsedBlock(region_id=1, text="NETO A PAGAR: 2500.00", page=0, bbox=[0, 0.1, 1, 0.2], confidence=0.9),
    ],
)


class Script:
    def __init__(self, *responses: Response) -> None:
        self.responses, self.requests = list(responses), []

    async def __call__(self, request: Request, ctx: object = None) -> Response:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else says("no sé")


def _tool_results(request: Request) -> list[str]:
    return [" ".join(p.text for p in r.content if isinstance(p, Text)) for m in request.messages for r in m.content if isinstance(r, ToolResult)]


async def _extract(script: Script, max_turns: int = 6, correction_note: str | None = None):
    settings = Settings(_env_file=None, extraction_max_turns=max_turns)
    async with port.inference_lifespan(settings, model=script, models={"reasoning": "razonador", "vision": "vlm"}):
        return await asyncio.to_thread(lambda: run_agentic_extraction(settings, PARSED, Boleta, purpose="extract/payslip/v1", hint="Es una boleta.", correction_note=correction_note))


@pytest.mark.asyncio
async def test_reads_a_region_then_submits_a_valid_result_with_its_trace():
    script = Script(calls("read_text_region", region_ids=[0, 1]), calls("submit", id="c2", empleado="ANA PEREZ", neto=2500.0))
    result, trace = await _extract(script)
    assert result == Boleta(empleado="ANA PEREZ", neto=2500.0)
    assert [(t.tool_name, t.arguments) for t in trace] == [("read_text_region", {"region_ids": [0, 1]})]
    assert "NETO A PAGAR: 2500.00" in trace[0].result_summary
    assert "NETO A PAGAR" in _tool_results(script.requests[1])[0]  # the model saw the real OCR text
    assert all(r.temperature == 0 and r.model == "razonador" for r in script.requests)


@pytest.mark.asyncio
async def test_an_invalid_submission_is_returned_with_its_error_and_corrected():
    script = Script(calls("submit", empleado="ANA", neto="mucho"), calls("submit", id="c2", empleado="ANA", neto=2500.0))
    result, _ = await _extract(script)
    assert result.neto == 2500.0 and len(script.requests) == 2
    assert "neto" in " ".join(_tool_results(script.requests[1]))


@pytest.mark.asyncio
async def test_a_tool_called_with_wrong_arguments_is_recoverable():
    script = Script(calls("read_text_region", region_id=0), calls("submit", id="c2", empleado="ANA", neto=1.0))
    result, _ = await _extract(script)
    assert result.empleado == "ANA"
    assert "region_ids" in " ".join(_tool_results(script.requests[1]))  # the binding error went back to the model


@pytest.mark.asyncio
async def test_never_submitting_within_the_turn_cap_is_incomplete():
    script = Script(*[calls("read_text_region", id=f"c{i}", region_ids=[0]) for i in range(5)])
    with pytest.raises(ExtractionIncomplete, match="LimitExceeded"):
        await _extract(script, max_turns=3)
    assert len(script.requests) == 3


@pytest.mark.asyncio
async def test_the_correction_note_reaches_the_model():
    script = Script(calls("submit", empleado="ANA", neto=1.0))
    await _extract(script, correction_note="el neto está en la región 1")
    first = " ".join(p.text for m in script.requests[0].messages for p in m.content if isinstance(p, Text))
    assert "el neto está en la región 1" in first
