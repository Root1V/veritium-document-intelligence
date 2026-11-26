"""PaddleOCR adapter for ``ParserBackend`` — generalizes the PoC's OCR +
LayoutDetection combination (text/polygon/confidence extraction plus
structural region detection for tables/figures/titles) into the
backend-agnostic ``ParsedDocument`` shape.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

# Must be set before importing paddleocr/paddlex — otherwise import-time
# network connectivity checks to the model hoster can hang in restricted
# network environments.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from paddleocr import LayoutDetection, PaddleOCR, TableStructureRecognition  # noqa: E402

from idp.config import Settings
from idp.parsing.normalize import ParsedBlock, ParsedDocument, load_pages, page_to_b64
from idp.parsing.tables import Line, cell_boxes, to_html

_LAYOUT_TYPES = {"table", "figure", "chart", "title", "seal"}  # seal: VRT-118


class PaddleOCRBackend:
    """Instantiated once (via DI) and reused — models load lazily on first
    ``parse()`` call, never at import time (unlike the PoC's module-level
    ``layout_engine = LayoutDetection()``)."""

    name = "paddleocr"

    def __init__(self, settings: Settings) -> None:
        self._lang = settings.ocr_language
        self._ocr: PaddleOCR | None = None
        self._layout: LayoutDetection | None = None
        self._tables: TableStructureRecognition | None = None

    def _ocr_engine(self) -> PaddleOCR:
        if self._ocr is None:
            # No page unwarping nor orientation correction: they make the OCR
            # read a transformed image, so its boxes stop matching the page
            # the reviewer sees (measured ~20 px off on a flat scan; worse on
            # photos). Evidence has to point at the original (VRT-38).
            self._ocr = PaddleOCR(lang=self._lang, use_doc_unwarping=False, use_doc_orientation_classify=False)
        return self._ocr

    def _layout_engine(self) -> LayoutDetection:
        if self._layout is None:
            self._layout = LayoutDetection()
        return self._layout

    def _table_engine(self) -> TableStructureRecognition:
        if self._tables is None:
            self._tables = TableStructureRecognition(model_name="SLANet_plus")
        return self._tables

    def _table_html(self, image_array: np.ndarray, box: tuple[int, int, int, int], lines: list[Line]) -> str:
        """The table as HTML, or "" when it was built wrong (VRT-120, parsing/tables.py)."""
        x1, y1, x2, y2 = box
        inside = [line for line in lines if x1 <= line.centre[0] <= x2 and y1 <= line.centre[1] <= y2]
        if len(inside) < 2:
            return ""
        out = next(iter(self._table_engine().predict(image_array[y1:y2, x1:x2])))
        heights = sorted(line.box[3] - line.box[1] for line in inside)
        return to_html(list(out["structure"]), cell_boxes(out["bbox"], (x1, y1)), inside, heights[len(heights) // 2]) or ""

    def _read_lines(self, image_array: np.ndarray) -> list[tuple[str, float, Any]]:
        """Each text line on the page: its text, confidence and polygon (pixels of this image)."""
        return [line for res in self._ocr_engine().predict(image_array) for line in zip(res.get("rec_texts", []), res.get("rec_scores", []), res.get("rec_polys", []))]

    def parse(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        pages = load_pages(file_bytes, filename)
        blocks: list[ParsedBlock] = []
        page_images_b64: dict[int, str] = {}
        region_id = 0

        for page_index, image in enumerate(pages):
            width, height = image.size
            page_images_b64[page_index] = page_to_b64(image)
            image_array = np.array(image)

            lines: list[Line] = []
            for text, score, poly in self._read_lines(image_array):
                xs = [float(p[0]) for p in poly]
                ys = [float(p[1]) for p in poly]
                lines.append(Line(region_id, text, (min(xs), min(ys), max(xs), max(ys))))
                bbox = [min(xs) / width, min(ys) / height, max(xs) / width, max(ys) / height]
                blocks.append(
                    ParsedBlock(
                        region_id=region_id,
                        text=text,
                        page=page_index,
                        bbox=bbox,
                        confidence=float(score),
                        block_type="text",
                    )
                )
                region_id += 1

            for res in self._layout_engine().predict(image_array):
                for box in res.get("boxes", []):
                    label = box.get("label", "text")
                    score = float(box.get("score", 0.0))
                    x1, y1, x2, y2 = box.get("coordinate", [0.0, 0.0, 0.0, 0.0])
                    bbox = [x1 / width, y1 / height, x2 / width, y2 / height]
                    block_type = label if label in _LAYOUT_TYPES else "text"
                    text = self._table_html(image_array, (int(x1), int(y1), int(x2), int(y2)), lines) if block_type == "table" else ""
                    blocks.append(
                        ParsedBlock(
                            region_id=region_id,
                            text=text,
                            page=page_index,
                            bbox=bbox,
                            confidence=score,
                            block_type=block_type,
                        )
                    )
                    region_id += 1

        return ParsedDocument(backend=self.name, page_count=len(pages), blocks=blocks, page_images_b64=page_images_b64)
