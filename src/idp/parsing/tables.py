"""Tables as tables (VRT-120): the layout finds a table, SLANet_plus finds its
rows, columns and merged cells, and each cell is filled with the OCR lines
whose centre falls in it. The agent gets HTML that keeps a merged header over
its columns, and each cell names the region_ids of its lines (r="12,13"): a
value read from a cell is grounded to its line, not to the whole table.

A table the model built wrong is worse than none: one that puts several rows
in a cell, or collapses into a single column, or leaves lines out, is
dropped, and the agent reads its lines as before. Measured on the 11
documents (2026-11-25): ruled tables come out right, most unruled printed
ones too; a dense payslip and a photo with handwritten marks do not."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

_CELL = re.compile(r"<td([^>]*)>")
_MAX_MERGED = 0.05  # share of filled cells allowed to hold lines of more than one row
_MIN_PLACED = 0.9  # share of the table's OCR lines that must land in a cell


@dataclass(frozen=True)
class Line:
    region_id: int
    text: str
    box: tuple[float, float, float, float]  # pixels of the page: x1, y1, x2, y2

    @property
    def centre(self) -> tuple[float, float]:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2


def cell_boxes(raw: Any, offset: tuple[float, float]) -> list[tuple[float, float, float, float]]:
    """SLANet gives each cell as 8 numbers (4 corners) in the crop; to page pixels."""
    out = []
    for poly in raw:
        xs, ys = np.asarray(poly[0::2], dtype=float) + offset[0], np.asarray(poly[1::2], dtype=float) + offset[1]
        out.append((float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())))
    return out


def to_html(structure: list[str], cells: list[tuple[float, float, float, float]], lines: list[Line], line_height: float) -> str | None:
    """``structure``: SLANet's tokens; ``cells``: one box per <td>, in page pixels;
    ``lines``: the OCR lines inside the table. None when the table is not trustworthy."""
    markup = "".join(structure).replace("<html><body>", "").replace("</body></html>", "")
    attrs = _CELL.findall(markup)
    if not attrs or len(attrs) != len(cells) or not lines:
        return None
    content: list[list[Line]] = [[] for _ in cells]
    for line in lines:
        x, y = line.centre
        hit = next((i for i, c in enumerate(cells) if c[0] <= x <= c[2] and c[1] <= y <= c[3]), None)
        if hit is not None:
            content[hit].append(line)
    filled = [(a, found) for a, found in zip(attrs, content) if found]
    merged = sum(1 for a, found in filled if "rowspan" not in a and max(f.centre[1] for f in found) - min(f.centre[1] for f in found) > 1.5 * line_height)
    columns = max(len(_CELL.findall(row)) for row in markup.split("<tr>"))
    if merged > _MAX_MERGED * len(filled) or columns < 2 or sum(len(f) for _, f in filled) < _MIN_PLACED * len(lines):
        return None
    cells_content = iter(content)

    def cell(match: re.Match[str]) -> str:
        found = sorted(next(cells_content), key=lambda line: (round(line.box[1] / line_height), line.box[0]))
        ids = f' r="{",".join(str(f.region_id) for f in found)}"' if found else ""
        return f"<td{match.group(1)}{ids}>" + html.escape(" ".join(f.text for f in found))

    return _CELL.sub(cell, markup)
