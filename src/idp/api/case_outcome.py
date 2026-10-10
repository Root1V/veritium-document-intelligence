"""Where a case stands, short and in business words — what an agent gets
from the MCP tools (VRT-51) and the A2A tasks (VRT-52) to decide its next
step. The full result contract stays one read away."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.case_contract import latest_run
from idp.domain.case_progress import progress
from idp.persistence.models import Case
from idp.pipeline.orchestrator import case_document_fields, load_semantic_catalog, resolve_semantic_view
from idp.persistence.repositories import CaseConditionRepository, DocumentRepository, DocumentTypeRepository

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


_AGREEMENT = {"consistent": "los documentos coinciden", "conflict": "los documentos no coinciden", "single_source": "una sola fuente"}


class SourceEvidence(BaseModel):
    document: str = Field(description="Tipo y archivo del documento.")
    field: str
    value: Any
    page: int | None = Field(description="Página del documento (la primera es 1).")
    bbox: list[float] | None = Field(description="Posición en la página (x1, y1, x2, y2 relativos).")
    confidence: float | None
    source_text: str | None


class FieldEvidence(BaseModel):
    attribute: str
    name: str
    role: str
    value: Any
    agreement: str
    sources: list[SourceEvidence]


async def field_evidence(session: AsyncSession, case: Case, attribute: str, role: str = "titular") -> FieldEvidence:
    """Where a datum of the case comes from (VRT-53). ``attribute`` by key
    ('persona.dni') or by business name ('DNI'). LookupError names what exists."""
    version = case.profile_version.semantic_catalog_version if case.profile_version else None
    loaded = await load_semantic_catalog(session, version)
    view = await resolve_semantic_view(session, await case_document_fields(DocumentRepository(session), case.id), catalog_version=version)
    if loaded is None or view is None:
        raise LookupError("este expediente no tiene vista consolidada de datos")
    catalog = loaded[0]
    names = {a.key: a.name for a in catalog.attributes}
    wanted = attribute.strip().lower()
    key = next((k for k, n in names.items() if wanted in (k.lower(), n.lower())), attribute)
    resolved = view.get(role, key)
    if resolved is None:
        available = sorted(names.get(r.attribute, r.attribute) for r in view.attributes if r.role == role)
        raise LookupError(f"el expediente no tiene '{attribute}' para el rol {role}; tiene: {', '.join(available) or 'ningún dato'}")
    types = await DocumentTypeRepository(session).load_catalog()
    type_names = {k: c[1].display_name for k in types.keys() if (c := types.current(k))}
    documents = {d.id: f"{type_names.get(d.document_type or '', d.document_type or 'Documento')} ({d.original_filename})" for d in case.documents}
    return FieldEvidence(
        attribute=key, name=names.get(key, key), role=role, value=resolved.value, agreement=_AGREEMENT.get(resolved.status, resolved.status),
        sources=[
            SourceEvidence(
                document=documents.get(s.document_id, str(s.document_id)), field=s.field_path, value=s.value, page=s.page + 1 if s.page is not None else None, bbox=s.bbox,
                confidence=s.confidence, source_text=s.source_text,
            )
            for s in resolved.sources
        ],
    )
