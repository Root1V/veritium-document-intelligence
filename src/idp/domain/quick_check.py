"""The quick check of an uploaded file (VRT-47), the pure part: from what
was measured on a file, whether it can be read, and what to tell the
person who uploaded it — in seconds, while they can still take the photo
again. Only what would make the file unreadable rejects it; the rest
warns. The thresholds were measured on real documents: sharp pages score
115 to 6700 in sharpness (variance of the Laplacian at 1000 px wide) and
blurred ones 1 to 10; normal pages average 160 to 250 in brightness and
darkened ones 55 to 90."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Level = Literal["ok", "warning", "reject"]

SHARP_REJECT, SHARP_WARN = 15.0, 60.0
DARK_REJECT, DARK_WARN = 50.0, 100.0
BLANK_CONTRAST = 6.0
SIDE_REJECT, SIDE_WARN = 600, 900  # shortest side of a photo, in pixels


class PageStats(BaseModel):
    page: int  # 0-based
    width: int
    height: int
    sharpness: float
    brightness: float
    contrast: float


class FileFacts(BaseModel):
    """What was measured on a file. ``problem`` is set when it could not be
    opened at all (damaged, password, unsupported format)."""

    kind: Literal["pdf", "image", "unknown"]
    page_count: int = 0
    text_chars: int | None = None  # PDF text layer, when there is one
    pages: list[PageStats] = []
    problem: str | None = None


class Check(BaseModel):
    code: str
    level: Level
    message: str


def assess(facts: FileFacts, *, expected_type: str | None = None, detected_type: str | None = None, type_names: dict[str, str] | None = None) -> list[Check]:
    names = type_names or {}
    if facts.problem is not None:
        return [Check(code="unreadable", level="reject", message=facts.problem)]
    checks: list[Check] = []
    # Blank is light and flat; dark and flat is a photo with no light.
    blank = [p.page for p in facts.pages if p.contrast < BLANK_CONTRAST and p.brightness >= DARK_WARN]
    if blank and len(blank) == len(facts.pages):
        return [Check(code="blank", level="reject", message="El archivo parece estar en blanco. Revisa que sea el documento correcto.")]
    if blank:
        checks.append(Check(code="blank_page", level="warning", message=f"La página {blank[0] + 1} parece estar en blanco."))
    # A blank page says nothing about sharpness or light.
    content = [p for p in facts.pages if p.page not in blank]
    worst_sharp = min((p.sharpness for p in content), default=None)
    darkest = min((p.brightness for p in content), default=None)
    photo = facts.kind == "image"
    shortest = min((min(p.width, p.height) for p in facts.pages), default=None)

    if worst_sharp is not None and worst_sharp < SHARP_REJECT:
        checks.append(Check(code="blurry", level="reject", message="La imagen está muy borrosa y no se puede leer. Tómala de nuevo, sin mover el teléfono y con buena luz."))
    elif worst_sharp is not None and worst_sharp < SHARP_WARN:
        checks.append(Check(code="soft", level="warning", message="La imagen está algo borrosa. Si puedes, tómala de nuevo con el teléfono quieto."))
    if darkest is not None and darkest < DARK_REJECT:
        checks.append(Check(code="dark", level="reject", message="La imagen está demasiado oscura. Tómala de nuevo con más luz."))
    elif darkest is not None and darkest < DARK_WARN:
        checks.append(Check(code="dim", level="warning", message="La imagen está algo oscura. Si puedes, tómala con más luz."))
    if photo and shortest is not None and shortest < SIDE_REJECT:
        checks.append(Check(code="tiny", level="reject", message="La imagen tiene muy poca resolución. Tómala más de cerca o con la cámara del teléfono."))
    elif photo and shortest is not None and shortest < SIDE_WARN:
        checks.append(Check(code="small", level="warning", message="La imagen tiene poca resolución; puede que algunos datos no se lean bien."))
    if expected_type and detected_type and detected_type not in (expected_type, "otro"):
        checks.append(
            Check(
                code="other_type",
                level="warning",
                message=f"Parece ser {names.get(detected_type, detected_type)}, no {names.get(expected_type, expected_type)}. Revisa que sea el documento pedido.",
            )
        )
    if not checks:
        checks.append(Check(code="ok", level="ok", message="Se ve bien."))
    return checks


def verdict(checks: list[Check]) -> Level:
    levels = {c.level for c in checks}
    return "reject" if "reject" in levels else "warning" if "warning" in levels else "ok"
