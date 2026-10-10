"""What the MCP tools answer (VRT-51): short, in business words, enough for
an agent to decide its next step; the full result contract stays one
resource away (``veritium://cases/{id}/result``)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.case_contract import latest_run
from idp.domain.case_progress import progress
from idp.persistence.models import Case
from idp.persistence.repositories import CaseConditionRepository, DocumentTypeRepository

VERDICT_LABEL = {"continue": "Continuar", "human_review": "Revisión humana", "return_to_client": "Devolver al cliente"}


class CaseOutcome(BaseModel):
    """Where a case stands. While it runs only ``status`` and ``progress``
    say something; once done, ``verdict`` and its reasons."""

    case_id: uuid.UUID
    external_ref: str | None
    run_number: int | None
    status: Literal["processing", "completed", "failed"]
    progress: str = Field(description="Qué está pasando ahora, en palabras.")
    verdict: Literal["continue", "human_review", "return_to_client"] | None = None
    verdict_label: str | None = None
    reasons: list[str] = Field(default_factory=list, description="Por qué ese veredicto; cada motivo una vez.")
    missing: list[str] = Field(default_factory=list, description="Requisitos del proceso aún pendientes (documentos o evidencias).")
    documents: list[str] = Field(default_factory=list, description="Documentos recibidos, con el tipo reconocido.")
    result_uri: str = Field(description="Recurso MCP con el resultado completo (contrato v1, JSON).")


async def case_outcome(session: AsyncSession, case: Case) -> CaseOutcome:
    run = latest_run(case)
    run_status = run.status if run else None
    status: Literal["processing", "completed", "failed"] = (
        "completed" if run_status == "completed" else "failed" if run_status == "failed" else "processing"
    )
    outcome = CaseOutcome(
        case_id=case.id,
        external_ref=case.external_ref,
        run_number=run.run_number if run else None,
        status=status,
        progress=progress(case.status, run_status, [d.status for d in case.documents]).current,
        result_uri=f"veritium://cases/{case.id}/result",
    )
    if status == "failed":
        outcome.reasons = [f"El proceso se detuvo por un error: {(run.error or '').split(':', 1)[0]}"] if run else []
        return outcome
    if status == "processing":
        return outcome
    catalog = await DocumentTypeRepository(session).load_catalog()
    names = {key: current[1].display_name for key in catalog.keys() if (current := catalog.current(key))}
    outcome.verdict = case.verdict  # type: ignore[assignment]
    outcome.verdict_label = VERDICT_LABEL.get(case.verdict or "")
    outcome.reasons = list(dict.fromkeys(r.get("message", "") for r in case.verdict_reasons or []))
    outcome.missing = [c.label for c in (await CaseConditionRepository(session).latest_by_key(case.id)).values() if c.status == "open"]
    segmented = {d.parent_document_id for d in case.documents if d.parent_document_id}
    outcome.documents = [
        f"{d.original_filename}: {names.get(d.document_type or '', d.document_type or 'sin clasificar')}" + (" (con campos por revisar)" if d.needs_review else "")
        for d in case.documents
        if d.id not in segmented
    ]
    return outcome
