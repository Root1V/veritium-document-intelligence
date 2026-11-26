"""The backend-agnostic parsed-document representation. Every ``ParserBackend``
implementation normalizes its native output into this shape *before* anything
downstream touches it, so the citation envelope (``domain.envelope.Extracted``)
always has a grounding source regardless of which backend ran.
"""

from __future__ import annotations

import base64
import io

from PIL import Image
from pydantic import BaseModel, Field

BlockType = str  # "text" | "table" | "figure" | "title"


class ParsedBlock(BaseModel):
    """One OCR/layout element: a line, paragraph, table, or figure region."""

    region_id: int
    text: str
    page: int
    bbox: list[float]  # normalized [x1, y1, x2, y2] in [0, 1], relative to the page
    confidence: float
    block_type: BlockType = "text"

    @property
    def read(self) -> bool:
        """Text the OCR read on the page. A table's text is its HTML built from those same lines (VRT-120): counted once."""
        return self.block_type not in ("figure", "table")


class ParsedDocument(BaseModel):
    backend: str
    page_count: int
    blocks: list[ParsedBlock] = Field(default_factory=list)
    # Per-page PNG bytes (base64-free here; kept as raw bytes for in-process
    # use), needed by the agentic extraction loop's region-crop tools.
    page_images_b64: dict[int, str] = Field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.read)

    def block(self, region_id: int) -> ParsedBlock | None:
        return next((b for b in self.blocks if b.region_id == region_id), None)

    def blocks_of_type(self, block_type: BlockType) -> list[ParsedBlock]:
        return [b for b in self.blocks if b.block_type == block_type]


def slice_by_pages(parsed: ParsedDocument, start_page: int, end_page: int) -> ParsedDocument:
    """A view of ``parsed`` restricted to one physical-upload page range —
    used when segmentation finds more than one logical document bundled in
    a single upload. Absolute page numbers are kept as-is (not renumbered to
    0 for the slice) so grounding/citations still point at the original
    physical document's page, matching what a human reviewer sees."""
    return ParsedDocument(
        backend=parsed.backend,
        page_count=parsed.page_count,
        blocks=[b for b in parsed.blocks if start_page <= b.page <= end_page],
        page_images_b64={p: img for p, img in parsed.page_images_b64.items() if start_page <= p <= end_page},
    )


def load_pages(file_bytes: bytes, filename: str) -> list[Image.Image]:
    """Renders a document to one RGB image per page. Shared by every
    ``ParserBackend`` so page-image grounding for the agentic loop's
    region-crop tools is identical regardless of which backend parsed the
    text/layout content."""
    if filename.lower().endswith(".pdf"):
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(file_bytes)
        return [page.render(scale=2.0).to_pil().convert("RGB") for page in pdf]
    return [Image.open(io.BytesIO(file_bytes)).convert("RGB")]


def page_to_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
