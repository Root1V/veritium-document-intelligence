"""Whether a document is signed or sealed (VRT-118): a requirement banks
check by hand — «la carta de autorización debe estar firmada» — and the
extraction never looked at.

A seal comes free with the reading: the layout model labels it (0.92–0.93 on
the bench's two sealed documents). A signature it labels as just an image,
so the vision model looks at the pages that ask for one — only for the types
a process requires signed: a call per document nobody asked for is waste."""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from idp.llm.prompts import prompt
from idp.parsing.normalize import ParsedDocument

_LOOK = prompt(
    "check_signature",
    "Is this page signed? A signature is a handwritten mark in ink, or a digital signature stamp — a printed name, an empty "
    "signature line or a typed «Firma:» label is NOT a signature. Answer SIGNED or UNSIGNED as your first word, then say where in one short sentence.",
)
_ASKS_FOR_IT = re.compile(r"firma|suscri|conformidad", re.IGNORECASE)
_MAX_PAGES = 2


class Attestations(BaseModel):
    sealed_pages: list[int] = []
    # None: not looked at (no process asked for it, or the vision model did not answer).
    signed: bool | None = None
    signed_pages: list[int] = []

    @property
    def sealed(self) -> bool:
        return bool(self.sealed_pages)


def seals(parsed: ParsedDocument) -> list[int]:
    return sorted({b.page for b in parsed.blocks if b.block_type == "seal"})


def signature_pages(parsed: ParsedDocument) -> list[int]:
    """Where a signature would be: pages that mention one, else the last page."""
    asked = sorted({b.page for b in parsed.blocks if _ASKS_FOR_IT.search(b.text)})
    pages = asked or ([max(parsed.page_images_b64)] if parsed.page_images_b64 else [])
    return pages[-_MAX_PAGES:]


async def attest(parsed: ParsedDocument, *, check_signature: bool) -> Attestations:
    out = Attestations(sealed_pages=seals(parsed))
    if not check_signature:
        return out
    from idp.llm.port import inference

    signed: list[int] = []
    try:
        for page in signature_pages(parsed):
            answer = await inference().vision(purpose="check_signature", image_b64=parsed.page_images_b64[page], prompt=str(_LOOK))
            if answer.strip().upper().startswith("SIGNED"):
                signed.append(page)
    except Exception:  # an unanswered check is not an unsigned document: a person looks
        logging.getLogger(__name__).warning("no se pudo comprobar la firma", exc_info=True)
        return out
    return out.model_copy(update={"signed": bool(signed), "signed_pages": signed})
