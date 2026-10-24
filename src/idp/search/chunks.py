"""What of a document is searchable, as pieces (pure): one with its
extracted values, "field: value" per line, and windows of the text read
from each page. A window is small enough for the embedding to mean
something and for a hit to say on which page it is; consecutive windows
overlap so a phrase cut by a boundary is still found whole."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal

from idp.parsing.normalize import ParsedDocument

WINDOW_CHARS = 1200
OVERLAP_CHARS = 200


@dataclass(frozen=True)
class Chunk:
    kind: Literal["valores", "texto"]
    page: int | None  # 0-indexed page of the file, for a text window
    content: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()


def _label(path: list[str]) -> str:
    return " ".join(p.replace("_", " ") for p in path)


def _lines(node: Any, path: list[str]) -> list[str]:
    if isinstance(node, dict):
        if "value" in node and "confidence" in node:  # an Extracted[T]
            return _lines(node["value"], path)
        return [line for key, value in node.items() for line in _lines(value, [*path, key])]
    if isinstance(node, list):
        return [line for item in node for line in _lines(item, path)]
    if node is None or node == "":
        return []
    return [f"{_label(path)}: {node}"]


def values_chunk(payload: dict[str, Any] | None) -> Chunk | None:
    lines = _lines(payload or {}, [])
    return Chunk("valores", None, "\n".join(lines)) if lines else None


def _windows(text: str) -> list[str]:
    if len(text) <= WINDOW_CHARS:
        return [text]
    windows, start = [], 0
    while start < len(text):
        end = min(start + WINDOW_CHARS, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + WINDOW_CHARS - OVERLAP_CHARS, end)
            end = cut if cut > start else end
        windows.append(text[start:end].strip())
        if end >= len(text):
            break
        back = text.find(" ", end - OVERLAP_CHARS, end)  # the overlap starts on a word, not inside one
        start = back + 1 if back > start else end
    return [w for w in windows if w]


def text_chunks(parsed: ParsedDocument | None, pages: tuple[int, int] | None = None) -> list[Chunk]:
    """Windows of each page's text; ``pages`` (first, last) limits them to a segment of the file."""
    if parsed is None:
        return []
    by_page: dict[int, list[str]] = {}
    for block in parsed.blocks:
        if block.block_type == "figure" or (pages is not None and not pages[0] <= block.page <= pages[1]):
            continue
        by_page.setdefault(block.page, []).append(block.text)
    return [
        Chunk("texto", page, window)
        for page in sorted(by_page)
        for window in _windows(re.sub(r"\s+", " ", " ".join(by_page[page])).strip())
    ]


def document_chunks(payload: dict[str, Any] | None, parsed: ParsedDocument | None, pages: tuple[int, int] | None = None) -> list[Chunk]:
    values = values_chunk(payload)
    return ([values] if values else []) + text_chunks(parsed, pages)
