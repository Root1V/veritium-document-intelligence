"""The bounded agentic extraction loop's fixed toolset (VRT-30): synaptum
``@tool`` functions bound to one parsed document. Only
``read_table_region``/``read_figure_region`` cost a VLM call (through the
InferencePort, awaited: tools run on the port's loop);
``read_text_region`` reads already-parsed text for free. ``look_closer``
and ``look_at_page`` (VRT-113) let the agent see what the OCR may have lost
or misread — a blurred value, a ticked box, a stamp — before deciding a
value or that it cannot be read. A call with the
wrong arguments is returned to the model as an error (synaptum S-3), so the
tools take exactly one shape.
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any

from PIL import Image
from synaptum import Tool, tool

from idp.llm.port import inference
from idp.llm.prompts import prompt
from idp.observability.otel import traced_tool_call
from idp.extraction.grounding import find_source_block
from idp.extraction.self_check import DraftChecker
from idp.parsing.normalize import ParsedDocument
from idp.tools.catalog import spec

_TABLE_PROMPT = prompt("read_table_region", "Describe the content of this table in a structured way: headers, rows and relevant values. Copy text and numbers exactly as they appear; never translate them.")
_LOOK_PROMPT = prompt("look_closer", "Answer only from what you see in this image. The answer is what is printed right after (or below) the label the question names — never a value printed for another label. If that spot holds a smudge, a blur, a blank or marks you cannot read, answer UNREADABLE and say why. Copy text and numbers exactly; never compute or guess them.")
_FIGURE_PROMPT = prompt("read_figure_region", "Describe the content of this figure/chart: its kind, axes or labels, and the relevant data or trends. Copy labels and numbers exactly as they appear; never translate them.")


def _crop_region_b64(parsed: ParsedDocument, region_id: int) -> str | None:
    block = parsed.block(region_id)
    if block is None:
        return None
    page_b64 = parsed.page_images_b64.get(block.page)
    if page_b64 is None:
        return None
    image = Image.open(io.BytesIO(base64.b64decode(page_b64)))
    width, height = image.size
    x1, y1, x2, y2 = block.bbox
    pad = 10
    box = (
        max(0, int(x1 * width) - pad),
        max(0, int(y1 * height) - pad),
        min(width, int(x2 * width) + pad),
        min(height, int(y2 * height) + pad),
    )
    cropped = image.crop(box)
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _png_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _beside_b64(parsed: ParsedDocument, label: str) -> str | None:
    """From a label to the page's right edge and a few lines below,
    enlarged: where its value is, even when the OCR lost it — and then it
    has no region of its own to crop. Nothing to the left: a value printed
    there belongs to another label and the vision model would take it. The
    label is found by its text, not by a region_id: the agent gave the id of
    the value beside it (measured on a blurred net pay, 2026-11-22)."""
    block = find_source_block(label, parsed)
    page_b64 = parsed.page_images_b64.get(block.page) if block is not None else None
    if block is None or page_b64 is None:
        return None
    image = Image.open(io.BytesIO(base64.b64decode(page_b64)))
    width, height = image.size
    x1, y1, _, y2 = block.bbox
    line = max(y2 - y1, 0.02)
    band = image.crop((max(0, int((x1 - 0.02) * width)), max(0, int((y1 - line) * height)), width, min(height, int((y2 + 3 * line) * height))))
    return _png_b64(band.resize((band.width * 2, band.height * 2), Image.Resampling.LANCZOS))


def _read_text(parsed: ParsedDocument, region_ids: list[int]) -> str:
    lines = []
    for region_id in region_ids:
        block = parsed.block(region_id)
        text = (block.text or "(sin texto)") if block is not None else "(region no encontrada)"
        lines.append(f"region_id={region_id}: {text}")
    return "\n".join(lines)


async def _read_visual(parsed: ParsedDocument, region_id: int, *, purpose: str, prompt: str) -> str:
    crop_b64 = await asyncio.to_thread(_crop_region_b64, parsed, region_id)
    if crop_b64 is None:
        return f"Region {region_id} no encontrada."
    return await inference().vision(purpose=purpose, image_b64=crop_b64, prompt=prompt)


def region_tools(parsed: ParsedDocument) -> list[Tool]:
    # Descriptions come from the tool catalog (VRT-53): it is what the model reads.
    @tool(idempotent=True, description=spec("read_text_region").description)
    async def read_text_region(region_ids: list[int]) -> str:
        with traced_tool_call(tool_name="read_text_region", arguments={"region_ids": region_ids}):
            return _read_text(parsed, region_ids)

    @tool(idempotent=True, description=spec("read_table_region").description)
    async def read_table_region(region_id: int) -> str:
        with traced_tool_call(tool_name="read_table_region", arguments={"region_id": region_id}):
            return await _read_visual(parsed, region_id, purpose="read_table_region", prompt=str(_TABLE_PROMPT))

    @tool(idempotent=True, description=spec("read_figure_region").description)
    async def read_figure_region(region_id: int) -> str:
        with traced_tool_call(tool_name="read_figure_region", arguments={"region_id": region_id}):
            return await _read_visual(parsed, region_id, purpose="read_figure_region", prompt=str(_FIGURE_PROMPT))

    @tool(idempotent=True, description=spec("look_closer").description)
    async def look_closer(label: str, question: str) -> str:
        with traced_tool_call(tool_name="look_closer", arguments={"label": label}):
            band = await asyncio.to_thread(_beside_b64, parsed, label)
            if band is None:
                return f"No encuentro la etiqueta '{label}' en el texto leido: usa look_at_page."
            return await inference().vision(purpose="look_closer", image_b64=band, prompt=f"{question}\n\n{_LOOK_PROMPT}")

    @tool(idempotent=True, description=spec("look_at_page").description)
    async def look_at_page(page: int, question: str) -> str:
        with traced_tool_call(tool_name="look_at_page", arguments={"page": page}):
            image = parsed.page_images_b64.get(page)
            if image is None:
                return f"Pagina {page} no encontrada."
            return await inference().vision(purpose="look_at_page", image_b64=image, prompt=f"{question}\n\n{_LOOK_PROMPT}")

    return [read_text_region, read_table_region, read_figure_region, look_closer, look_at_page]


def draft_tool(checker: DraftChecker) -> Tool:
    """The self-check (VRT-67): the document's own rules on the agent's draft."""

    @tool(idempotent=True, description=spec("check_draft").description)
    async def check_draft(values: dict[str, Any]) -> str:
        with traced_tool_call(tool_name="check_draft", arguments={"fields": sorted(values)}):
            problems = await checker.check(values)
        return "Sin problemas." if not problems else "Problemas encontrados:\n" + "\n".join(f"- {p}" for p in problems)

    return check_draft
