"""Why a human corrected an extracted field (VRT-39). A coded reason is
what makes corrections measurable — which ones point at OCR, which at the
extraction prompt or schema, which at the document itself — and feeds the
evaluation work of F4. The justification is free text; some reasons
require it because the code alone doesn't say enough."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ReasonCode = Literal[
    "ocr_misread",
    "wrong_source",
    "not_extracted",
    "format_normalization",
    "illegible_document",
    "business_override",
    "confirmed_correct",
]


class CorrectionReason(BaseModel):
    code: ReasonCode
    label: str
    description: str
    requires_justification: bool = False


CORRECTION_REASONS: list[CorrectionReason] = [
    CorrectionReason(code="ocr_misread", label="Error de lectura (OCR)", description="El dato está bien ubicado, pero se leyó mal (dígitos, letras, tildes)."),
    CorrectionReason(code="wrong_source", label="Se tomó otro dato", description="El valor viene de otro campo o región del documento."),
    CorrectionReason(code="not_extracted", label="No se extrajo", description="El dato está en el documento y quedó vacío."),
    CorrectionReason(code="format_normalization", label="Formato o normalización", description="El dato es el correcto, pero con otro formato (fecha, monto, mayúsculas)."),
    CorrectionReason(
        code="illegible_document", label="Documento ilegible", description="El dato no se puede leer en el documento.", requires_justification=True
    ),
    CorrectionReason(
        code="business_override", label="Decisión de negocio", description="Se usa otro valor por una razón del proceso, no del documento.", requires_justification=True
    ),
    CorrectionReason(code="confirmed_correct", label="El valor era correcto", description="Se confirma el valor extraído sin cambiarlo."),
]
REASONS_BY_CODE = {r.code: r for r in CORRECTION_REASONS}
