"""A human correction written into the extraction it corrects (VRT-40):
the leaf's value is replaced and its confidence set to 1.0, keeping its
page and bbox (the evidence is still where it was read). The original
value stays in the audit log. Re-extracting a document re-applies its
corrections, so a reprocess never silently undoes a human's work."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError

_PART = re.compile(r"(\w+)|\[(\d+)\]")


def apply_correction(payload: dict, field_path: str, value: Any, schema: type[BaseModel]) -> dict:
    """``payload`` with the corrected leaf, validated (and coerced, e.g.
    "1025.5" for a float field) against the extraction's schema. Raises
    ValueError when the path does not exist or the value does not fit."""
    corrected = schema.model_validate(payload).model_dump(mode="json")
    node: Any = corrected
    for name, index in _PART.findall(field_path):
        try:
            node = node[name] if name else node[int(index)]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"el campo '{field_path}' no existe en la extracción") from exc
    if not isinstance(node, dict) or "confidence" not in node:
        raise ValueError(f"'{field_path}' no es un campo extraído")
    node["value"], node["confidence"] = value, 1.0
    try:
        return schema.model_validate(corrected).model_dump(mode="json")
    except ValidationError as exc:
        raise ValueError(f"el valor no es válido para '{field_path}': {exc.errors()[0]['msg']}") from exc
