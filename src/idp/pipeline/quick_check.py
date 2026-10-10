"""The quick check of an uploaded file (VRT-47): open it, measure up to its
first pages (sharpness, brightness, contrast, size, text layer), and ask
the vision model which type it looks like — all within seconds. The type
is a hint with a time limit: when the model does not answer in time, the
full processing decides it."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from sqlalchemy.ext.asyncio import AsyncSession

from idp.config import Settings
from idp.domain.document_type_catalog import DocumentTypeCatalog
from idp.domain.quick_check import Check, FileFacts, Level, PageStats, assess, verdict
from idp.llm.port import inference
from idp.llm.prompts import prompt
from idp.persistence.repositories import DocumentTypeRepository

log = logging.getLogger(__name__)
MAX_PAGES_CHECKED = 3

_QUICK_TYPE = prompt(
    "quick_type",
    """Mira esta primera pagina de un documento que alguien acaba de subir. Responde SOLO con la clave de su tipo, \
una de estas (clave: descripcion):
{types}
o 'otro' si no es ninguno. Una sola palabra, sin explicacion.""",
    filled=("types",),
)


def _stats(image: Image.Image, page: int) -> PageStats:
    gray = image.convert("L")
    width = 1000
    gray = gray.resize((width, max(1, round(gray.height * width / gray.width))))
    a = np.asarray(gray, dtype=np.float32)
    laplacian = a[1:-1, 1:-1] * -4 + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    return PageStats(
        page=page, width=image.width, height=image.height,
        sharpness=round(float(laplacian.var()), 1), brightness=round(float(a.mean()), 1), contrast=round(float(a.std()), 1),
    )


def measure(data: bytes) -> tuple[FileFacts, Image.Image | None]:
    """What can be measured on a file, and its first page as an image."""
    if data[:5] == b"%PDF-":
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            message = "El PDF está protegido con contraseña. Súbelo sin contraseña." if "password" in str(exc).lower() else "El PDF está dañado y no se puede abrir."
            return FileFacts(kind="pdf", problem=message), None
        try:
            if len(pdf) == 0:
                return FileFacts(kind="pdf", problem="El PDF no tiene páginas."), None
            pages, chars, first = [], 0, None
            for i in range(min(len(pdf), MAX_PAGES_CHECKED)):
                page = pdf[i]
                chars += len(page.get_textpage().get_text_range().strip())
                image = page.render(scale=2).to_pil().convert("RGB")
                first = first or image
                pages.append(_stats(image, i))
            return FileFacts(kind="pdf", page_count=len(pdf), text_chars=chars, pages=pages), first
        finally:
            pdf.close()
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return FileFacts(kind="unknown", problem="No se reconoce el formato. Envía una foto JPG o PNG, o un PDF."), None
    return FileFacts(kind="image", page_count=1, pages=[_stats(image, 0)]), image


async def quick_type(settings: Settings, image: Image.Image, catalog: DocumentTypeCatalog) -> str | None:
    """The catalog type the first page looks like, 'otro', or None when the
    model did not answer within ``quick_check_type_timeout_seconds``."""
    page = image.copy()
    page.thumbnail((1024, 1024))
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=80)
    keys = catalog.keys()
    types = "\n".join(f"- {k}: {d.display_name}. {d.description}" for k in keys if (c := catalog.current(k)) is not None for d in [c[1]])
    try:
        answer = await asyncio.wait_for(
            inference().vision(
                purpose="quick_type", image_b64=base64.b64encode(buf.getvalue()).decode(), prompt=str(_QUICK_TYPE.render(types=types).render()), mime_type="image/jpeg"
            ),
            timeout=settings.quick_check_type_timeout_seconds,
        )
    except TimeoutError:
        return None
    except Exception:
        log.warning("quick type check failed", exc_info=True)
        return None
    word = answer.strip().strip("`'\".").split()[0].lower() if answer.strip() else ""
    return word if word in keys or word == "otro" else None


@dataclass(frozen=True)
class CheckedFile:
    facts: FileFacts
    detected_type: str | None  # a catalog type, 'otro', or None (unreadable, or the model did not answer in time)
    detected_type_name: str | None
    checks: list[Check]
    verdict: Level


async def check_file(settings: Settings, session: AsyncSession, data: bytes, *, expected_type: str | None = None) -> CheckedFile:
    """The whole quick check of one file — for upload sessions and for MCP (VRT-53)."""
    facts, first_page = await asyncio.to_thread(measure, data)
    catalog = await DocumentTypeRepository(session).load_catalog()
    detected = await quick_type(settings, first_page, catalog) if first_page is not None and facts.problem is None else None
    names = {k: c[1].display_name for k in catalog.keys() if (c := catalog.current(k))}
    checks = assess(facts, expected_type=expected_type, detected_type=detected, type_names=names)
    return CheckedFile(facts=facts, detected_type=detected, detected_type_name=names.get(detected or ""), checks=checks, verdict=verdict(checks))
