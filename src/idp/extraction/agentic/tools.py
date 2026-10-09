"""The bounded agentic extraction loop's fixed toolset (VRT-30): synaptum
``@tool`` functions bound to one parsed document. Only
``read_table_region``/``read_figure_region`` cost a VLM call (through the
InferencePort, awaited: tools run on the port's loop);
``read_text_region`` reads already-parsed text for free. A call with the
wrong arguments is returned to the model as an error (synaptum S-3), so the
tools take exactly one shape.
"""

from __future__ import annotations

import asyncio
import base64
import io

from PIL import Image
from synaptum import Tool, tool

from idp.llm.port import inference
from idp.llm.prompts import prompt
from idp.observability.otel import traced_tool_call
from idp.parsing.normalize import ParsedDocument

_TABLE_PROMPT = prompt("read_table_region", "Describe el contenido de esta tabla de forma estructurada: encabezados, filas y valores relevantes.")
_FIGURE_PROMPT = prompt("read_figure_region", "Describe el contenido de esta figura/grafico: tipo, ejes o etiquetas, y los datos o tendencias relevantes.")


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
    @tool(idempotent=True)
    async def read_text_region(region_ids: list[int]) -> str:
        """Lee el texto ya extraido (OCR) de una o varias regiones del documento por su region_id. Gratis, sin llamada a modelo de vision. Prefiere pasar VARIOS region_ids en una sola llamada (p. ej. todos los de una fila de tabla) en vez de una llamada por region — cada llamada consume un turno del presupuesto acotado del agente."""
        with traced_tool_call(tool_name="read_text_region", arguments={"region_ids": region_ids}):
            return _read_text(parsed, region_ids)

    @tool(idempotent=True)
    async def read_table_region(region_id: int) -> str:
        """Envia la imagen recortada de una region de tipo tabla a un modelo de vision para interpretar su contenido estructurado."""
        with traced_tool_call(tool_name="read_table_region", arguments={"region_id": region_id}):
            return await _read_visual(parsed, region_id, purpose="read_table_region", prompt=str(_TABLE_PROMPT))

    @tool(idempotent=True)
    async def read_figure_region(region_id: int) -> str:
        """Envia la imagen recortada de una region de tipo figura/grafico a un modelo de vision para interpretar su contenido."""
        with traced_tool_call(tool_name="read_figure_region", arguments={"region_id": region_id}):
            return await _read_visual(parsed, region_id, purpose="read_figure_region", prompt=str(_FIGURE_PROMPT))

    return [read_text_region, read_table_region, read_figure_region]
