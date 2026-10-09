"""PaddleOCR adapter for ``ParserBackend`` — generalizes the PoC's OCR +
LayoutDetection combination (text/polygon/confidence extraction plus
structural region detection for tables/figures/titles) into the
backend-agnostic ``ParsedDocument`` shape.
"""

from __future__ import annotations

import os

import numpy as np

# Must be set before importing paddleocr/paddlex — otherwise import-time
# network connectivity checks to the model hoster can hang in restricted
# network environments.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from paddleocr import LayoutDetection, PaddleOCR  # noqa: E402

from idp.config import Settings
from idp.parsing.normalize import ParsedBlock, ParsedDocument, load_pages, page_to_b64

_LAYOUT_TYPES = {"table", "figure", "chart", "title"}


class PaddleOCRBackend:
    """Instantiated once (via DI) and reused — models load lazily on first
    ``parse()`` call, never at import time (unlike the PoC's module-level
    ``layout_engine = LayoutDetection()``)."""

    name = "paddleocr"

    def __init__(self, settings: Settings) -> None:
        self._lang = settings.ocr_language
        self._ocr: PaddleOCR | None = None
        self._layout: LayoutDetection | None = None

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

    def parse(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        pages = load_pages(file_bytes, filename)
        blocks: list[ParsedBlock] = []
        page_images_b64: dict[int, str] = {}
        region_id = 0

        for page_index, image in enumerate(pages):
            width, height = image.size
            page_images_b64[page_index] = page_to_b64(image)
            image_array = np.array(image)

            for res in self._ocr_engine().predict(image_array):
                texts = res.get("rec_texts", [])
                scores = res.get("rec_scores", [])
                polys = res.get("rec_polys", [])
                for text, score, poly in zip(texts, scores, polys):
                    xs = [float(p[0]) for p in poly]
                    ys = [float(p[1]) for p in poly]
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
                    blocks.append(
                        ParsedBlock(
                            region_id=region_id,
                            text="",
                            page=page_index,
                            bbox=bbox,
                            confidence=score,
                            block_type=block_type,
                        )
                    )
                    region_id += 1

        return ParsedDocument(backend=self.name, page_count=len(pages), blocks=blocks, page_images_b64=page_images_b64)
