"""The default reader (VRT-70): PaddleOCR's models on ONNX Runtime read a
page's text with boxes on that same page. Needs the converted models
(scripts/export_ocr_onnx.sh); without them the reader says how to get them."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from PIL import Image, ImageDraw, ImageFont

from idp.config import Settings
from idp.parsing.rapidocr_backend import RapidOCRBackend


def _page(lines: list[str]) -> bytes:
    image = Image.new("RGB", (1000, 400), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((60, 60 + i * 110), line, fill="black", font=ImageFont.load_default(size=56))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_without_the_converted_models_it_says_how_to_get_them(tmp_path):
    with pytest.raises(RuntimeError, match="export_ocr_onnx.sh"):
        RapidOCRBackend(Settings(_env_file=None, ocr_onnx_dir=str(tmp_path))).parse(_page(["HOLA"]), "x.png")


@pytest.mark.skipif(not (Path(Settings(_env_file=None).ocr_onnx_dir).expanduser() / "PP-OCRv5_server_det.onnx").is_file(), reason="sin los modelos ONNX convertidos")
def test_reads_each_line_with_its_box_on_the_page():
    parsed = RapidOCRBackend(Settings(_env_file=None)).parse(_page(["NETO A PAGAR 3497.20", "DNI 42285866"]), "boleta.png")
    lines = [b for b in parsed.blocks if b.text]
    assert parsed.backend == "rapidocr" and parsed.page_count == 1
    assert any("3497.20" in b.text for b in lines) and any("42285866" in b.text for b in lines)
    dni = next(b for b in lines if "42285866" in b.text)
    x1, y1, x2, y2 = dni.bbox
    assert 0 <= x1 < x2 <= 1 and 0.3 < y1 < y2 <= 1, "the second line, lower on the page"
    assert 0.5 < dni.confidence <= 1
