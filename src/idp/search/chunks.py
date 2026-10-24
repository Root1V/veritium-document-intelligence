"""What of a document is searchable, as pieces (pure): its extracted
values, "field: value" per line, and windows of the text read
from each page. A window is small enough for the embedding to mean
something and for a hit to say on which page it is; consecutive windows
overlap so a phrase cut by a boundary is still found whole."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal

from idp.parsing.normalize import ParsedDocument

# The embedding and rerank servers take 512 tokens per input (llama.cpp's
# n_ubatch), query included. OCR text dense in numbers and symbols runs
# near a token per character: measured, 400 always fits and 500 not always.
WINDOW_CHARS = 400
OVERLAP_CHARS = 80


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


def values_chunks(payload: dict[str, Any] | None, context: str = "") -> list[Chunk]:
    """The values, whole lines grouped up to a window (a payslip's concepts run long)."""
    room = WINDOW_CHARS - len(context)
    groups: list[list[str]] = []
    for line in _lines(payload or {}, []):
        line = line[:room]
        if groups and sum(len(x) + 1 for x in groups[-1]) + len(line) <= room:
            groups[-1].append(line)
        else:
            groups.append([line])
    return [Chunk("valores", None, context + "\n".join(group)) for group in groups]


def _windows(text: str, size: int = WINDOW_CHARS) -> list[str]:
    if len(text) <= size:
        return [text]
    windows, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + size - OVERLAP_CHARS, end)
            end = cut if cut > start else end
        windows.append(text[start:end].strip())
        if end >= len(text):
            break
        back = text.find(" ", end - OVERLAP_CHARS, end)  # the overlap starts on a word, not inside one
        start = back + 1 if back > start else end
    return [w for w in windows if w]


def text_chunks(parsed: ParsedDocument | None, pages: tuple[int, int] | None = None, context: str = "") -> list[Chunk]:
    """Windows of each page's text; ``pages`` (first, last) limits them to a segment of the file."""
    if parsed is None:
        return []
    by_page: dict[int, list[str]] = {}
    for block in parsed.blocks:
        if block.block_type == "figure" or (pages is not None and not pages[0] <= block.page <= pages[1]):
            continue
        by_page.setdefault(block.page, []).append(block.text)
    return [
        Chunk("texto", page, context + window)
        for page in sorted(by_page)
        for window in _windows(re.sub(r"\s+", " ", " ".join(by_page[page])).strip(), WINDOW_CHARS - len(context))
    ]


def document_chunks(
    payload: dict[str, Any] | None, parsed: ParsedDocument | None, pages: tuple[int, int] | None = None, *, kind_of_document: str | None = None
) -> list[Chunk]:
    """``kind_of_document`` (the type's name, «Boleta de pago») heads every
    piece: a window of OCR text alone does not say what document it is from,
    and its embedding is much nearer a query that describes the document."""
    context = f"{kind_of_document}\n" if kind_of_document else ""
    return values_chunks(payload, context) + text_chunks(parsed, pages, context)
