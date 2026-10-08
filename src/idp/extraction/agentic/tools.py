"""The bounded agentic extraction loop's fixed toolset — a typed
generalization of the PoC's ``analyzeChart``/``analyzeTable`` LangChain
tools. Only ``read_table_region``/``read_figure_region`` cost a VLM call;
``read_text_region`` reads already-parsed text for free.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from PIL import Image

from idp.config import Settings
from idp.llm.port import vision
from idp.parsing.normalize import ParsedDocument

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_text_region",
            "description": (
                "Lee el texto ya extraido (OCR) de una o varias regiones del documento por su region_id. "
                "Gratis, sin llamada a modelo de vision. Prefiere pasar VARIOS region_ids en una sola "
                "llamada (p. ej. todos los de una fila de tabla) en vez de una llamada por region — "
                "cada llamada consume un turno del presupuesto acotado del agente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "IDs de las regiones a leer (una o varias en la misma llamada)",
                    }
                },
                "required": ["region_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_table_region",
            "description": "Envia la imagen recortada de una region de tipo tabla a un modelo de vision para interpretar su contenido estructurado.",
            "parameters": {
                "type": "object",
                "properties": {"region_id": {"type": "integer", "description": "ID de la region de tipo tabla"}},
                "required": ["region_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_figure_region",
            "description": "Envia la imagen recortada de una region de tipo figura/grafico a un modelo de vision para interpretar su contenido.",
            "parameters": {
                "type": "object",
                "properties": {"region_id": {"type": "integer", "description": "ID de la region de tipo figura"}},
                "required": ["region_id"],
            },
        },
    },
]

_TABLE_PROMPT = "Describe el contenido de esta tabla de forma estructurada: encabezados, filas y valores relevantes."
_FIGURE_PROMPT = "Describe el contenido de esta figura/grafico: tipo, ejes o etiquetas, y los datos o tendencias relevantes."


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


def read_text_region(parsed: ParsedDocument, region_ids: list[int]) -> str:
    lines = []
    for region_id in region_ids:
        block = parsed.block(region_id)
        text = (block.text or "(sin texto)") if block is not None else "(region no encontrada)"
        lines.append(f"region_id={region_id}: {text}")
    return "\n".join(lines)


def read_table_region(parsed: ParsedDocument, region_id: int, settings: Settings) -> str:
    crop_b64 = _crop_region_b64(parsed, region_id)
    if crop_b64 is None:
        return f"Region {region_id} no encontrada."
    return vision(purpose="read_table_region", image_b64=crop_b64, prompt=_TABLE_PROMPT)


def read_figure_region(parsed: ParsedDocument, region_id: int, settings: Settings) -> str:
    crop_b64 = _crop_region_b64(parsed, region_id)
    if crop_b64 is None:
        return f"Region {region_id} no encontrada."
    return vision(purpose="read_figure_region", image_b64=crop_b64, prompt=_FIGURE_PROMPT)


def _single_region_id(arguments: dict[str, Any]) -> int:
    if "region_id" in arguments:
        return int(arguments["region_id"])
    ids = arguments.get("region_ids") or []
    return int(ids[0]) if ids else -1


def dispatch_tool(name: str, arguments: dict[str, Any], parsed: ParsedDocument, settings: Settings) -> str:
    if name == "read_text_region":
        # Tolerate a model that still sends the older single region_id shape.
        region_ids = arguments.get("region_ids")
        if region_ids is None and "region_id" in arguments:
            region_ids = [arguments["region_id"]]
        return read_text_region(parsed, [int(r) for r in (region_ids or [])])
    if name == "read_table_region":
        return read_table_region(parsed, _single_region_id(arguments), settings)
    if name == "read_figure_region":
        return read_figure_region(parsed, _single_region_id(arguments), settings)
    return f"Herramienta desconocida: {name}"
