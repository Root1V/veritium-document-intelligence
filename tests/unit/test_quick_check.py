"""Unit tests for VRT-47's quick check: what is measured on a file and what
the person who uploaded it is told."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from idp.domain.quick_check import FileFacts, PageStats, assess, verdict
from idp.pipeline.quick_check import measure


def _document(size: tuple[int, int] = (1240, 1754)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for y in range(80, size[1] - 80, 28):
        draw.text((60, y), "BOLETA DE PAGO  Sueldo basico 2,420.80  Neto a pagar 4,304.14  DNI 42785091", fill="black")
    return image


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _levels(data: bytes, **kw) -> tuple[str, list[str]]:
    facts, _ = measure(data)
    checks = assess(facts, **kw)
    return verdict(checks), [c.code for c in checks]


def test_a_clean_page_passes() -> None:
    assert _levels(_png(_document())) == ("ok", ["ok"])


def test_a_blurred_photo_is_rejected_and_says_what_to_do() -> None:
    level, codes = _levels(_png(_document().filter(ImageFilter.GaussianBlur(4))))
    assert level == "reject" and "blurry" in codes
    facts, _ = measure(_png(_document().filter(ImageFilter.GaussianBlur(4))))
    assert "Tómala de nuevo" in next(c.message for c in assess(facts) if c.code == "blurry")


def test_a_dark_photo_warns_or_rejects_by_how_dark() -> None:
    assert "dim" in _levels(_png(ImageEnhance.Brightness(_document()).enhance(0.38)))[1]
    assert "dark" in _levels(_png(ImageEnhance.Brightness(_document()).enhance(0.15)))[1]


def test_a_tiny_photo_is_rejected() -> None:
    assert "tiny" in _levels(_png(_document((400, 560))))[1]


def test_a_blank_page_is_rejected() -> None:
    assert _levels(_png(Image.new("RGB", (1240, 1754), "white"))) == ("reject", ["blank"])


def test_a_file_that_cannot_be_opened_says_why() -> None:
    assert measure(b"hola, no soy un documento")[0].problem.startswith("No se reconoce el formato")  # type: ignore[union-attr]
    assert "dañado" in (measure(b"%PDF-1.4 roto")[0].problem or "")


def test_another_document_than_the_one_asked_for_warns() -> None:
    facts = FileFacts(kind="image", page_count=1, pages=[PageStats(page=0, width=1240, height=1754, sharpness=900, brightness=230, contrast=40)])
    checks = assess(facts, expected_type="payslip", detected_type="insurance_disclosure", type_names={"payslip": "Boleta de pago", "insurance_disclosure": "Declaración de seguro"})
    assert verdict(checks) == "warning" and checks[0].message.startswith("Parece ser Declaración de seguro, no Boleta de pago")
    assert verdict(assess(facts, expected_type="payslip", detected_type="otro")) == "ok", "an unknown type is left to the full processing"
