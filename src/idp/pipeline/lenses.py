"""Runs a lens over a case (VRT-45): gathers the text of the documents it
reads (kept at processing time; parsed once more for a document processed
before that), asks the model with every line numbered, and keeps the
answer with its citations resolved to page and box. Runs in the API
process, like a rule draft: one call, seconds to a minute."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from idp.config import Settings
from idp.domain.lenses import LensDefinition, LensDocument, LensSummaryAnswer, PlaybookAnswer, build_output, render_context, render_facts
from idp.llm.port import structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument
from idp.parsing.store import load_parsed, save_parsed
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case
from idp.persistence.repositories import CaseRepository, DocumentRepository, DocumentTypeRepository, LensRepository
from idp.pipeline.orchestrator import case_document_fields, load_semantic_catalog, parse_example, resolve_semantic_view
from idp.storage.object_store import S3ObjectStore

_COMMON = """Lees un expediente de credito. Primero vienen los datos que la plataforma ya extrajo y concilio entre \
documentos ([f1], [f2]...); luego el texto de cada documento, linea por linea ([d1:31] = documento 1, region 31). \
Parte de los datos ya extraidos: son confiables, y en el texto una etiqueta y su valor suelen estar en lineas \
separadas. Respeta los roles de los datos extraidos: el Titular es el cliente; el Asesor es personal de la \
entidad, nunca el cliente. Escribe en espanol claro, para un ejecutivo, sin jerga tecnica. Cita en `refs` las referencias exactas \
donde se apoya cada afirmacion. Copia nombres, montos y fechas exactamente como aparecen. No afirmes nada que no \
este en el expediente y no inventes cifras ni referencias."""

_SUMMARY = prompt("lens_summary", _COMMON + """

Eres analista del area de {area}. {instructions}
Responde con un titular de una o dos frases, de 3 a 8 puntos clave con sus referencias, y en `attention` como \
maximo 4 alertas que un analista debe revisar en ESTE expediente: datos que no coinciden, montos que no cuadran o \
datos clave que faltan. No incluyas generalidades que valdrian para cualquier expediente.""", filled=("area", "instructions"))

_PLAYBOOK = prompt("lens_playbook", _COMMON + """

Eres abogado del area {area}. Revisa CADA punto del playbook contra los documentos y responde un check por punto \
(item_key igual a la clave del punto):
- status: "cumple", "no_cumple" (el documento lo trata pero no como se exige), "no_encontrado" (el documento no lo \
trata) o "dudoso" (no se puede decidir con lo que dice).
- explanation: por que, en una o dos frases simples.
- quote: la cita textual mas corta del documento que lo muestra, copiada tal cual; null si no hay.
- refs: las referencias de esa cita.
Agrega un titular de una frase con la conclusion general.

Playbook:
{playbook}""", filled=("area", "playbook"))


async def lens_documents(settings: Settings, session: AsyncSession, case: Case, lens: LensDefinition) -> list[LensDocument]:
    """The case's logical documents the lens reads, with their text."""
    documents = await DocumentRepository(session).list_for_case(case.id)
    segmented = {d.parent_document_id for d in documents if d.parent_document_id is not None}
    types = await DocumentTypeRepository(session).load_catalog()
    store = S3ObjectStore(settings)
    parsed_by_file: dict[str, ParsedDocument] = {}
    out: list[LensDocument] = []
    for d in documents:
        if d.id in segmented or d.status == "failed" or (lens.document_types and d.document_type not in lens.document_types):
            continue
        parsed = parsed_by_file.get(d.storage_key) or await asyncio.to_thread(load_parsed, store, d.storage_key)
        if parsed is None:  # processed before the text was kept: read it once more, and keep it
            parsed = await asyncio.to_thread(parse_example, settings, await asyncio.to_thread(store.get, d.storage_key), d.original_filename)
            await asyncio.to_thread(save_parsed, store, d.storage_key, parsed)
        parsed_by_file[d.storage_key] = parsed
        current = types.current(d.document_type) if d.document_type else None
        type_name = current[1].display_name if current else (d.document_type or "Documento sin tipo")
        out.append(
            LensDocument(document_id=d.id, document_type=d.document_type, name=f"{type_name} ({d.original_filename})", parsed=parsed,
                         page_start=d.page_start, page_end=d.page_end)
        )
    return out


def _ask(settings: Settings, lens: LensDefinition, context: str) -> LensSummaryAnswer | PlaybookAnswer:
    area = "Riesgos" if lens.area == "riesgos" else "Legal"
    with traced_llm_call(role="reasoning", model=settings.reasoning_model):
        if lens.kind == "summary":
            return structured(purpose=f"lens/{lens.key}", role="reasoning", output=LensSummaryAnswer,
                              instructions=_SUMMARY.render(area=area, instructions=lens.instructions), task=context)
        playbook = "\n".join(f"- {i.key}: {i.label}" + (f" ({i.guidance})" if i.guidance else "") for i in lens.playbook)
        return structured(purpose=f"lens/{lens.key}", role="reasoning", output=PlaybookAnswer,
                          instructions=_PLAYBOOK.render(area=area, playbook=playbook), task=context)


async def run_lens(settings: Settings, result_id: uuid.UUID) -> None:
    async with get_session_factory(settings)() as session:
        repo = LensRepository(session)
        result = await repo.get_result(result_id)
        if result is None or result.status != "running":
            return
        try:
            lens = LensDefinition.model_validate(result.definition)
            case = await CaseRepository(session).get(result.case_id)
            if case is None:
                raise ValueError("el expediente ya no existe")
            documents = await lens_documents(settings, session, case, lens)
            if not documents:
                raise ValueError("el expediente no tiene documentos que esta lente lea")
            # The data already extracted and reconciled, from all the case's documents.
            catalog_version = case.profile_version.semantic_catalog_version if case.profile_version else None
            view = await resolve_semantic_view(session, await case_document_fields(DocumentRepository(session), case.id), catalog_version=catalog_version)
            loaded = await load_semantic_catalog(session, catalog_version)
            all_names = {d.id: f"{d.document_type or 'Documento'} ({d.original_filename})" for d in case.documents}
            all_names.update({d.document_id: d.name for d in documents})
            facts, fact_index = render_facts(view, loaded[0] if loaded else None, all_names)
            context, index, truncated = render_context(documents, facts, fact_index)
            answer = await asyncio.to_thread(_ask, settings, lens, context)
            result.output = build_output(lens, answer, index, truncated=truncated).model_dump(mode="json")
            result.status, result.model = "done", settings.reasoning_model
        except Exception as exc:
            result.status, result.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        result.finished_at = datetime.now(UTC)
        await session.commit()
