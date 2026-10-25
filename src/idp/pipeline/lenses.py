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
from idp.llm.port import charged_to, model_for, resolved_models, structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument
from idp.parsing.store import load_parsed, save_parsed
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case
from idp.persistence.repositories import CaseRepository, DocumentRepository, DocumentTypeRepository, LensRepository
from idp.pipeline.orchestrator import case_document_fields, load_semantic_catalog, parse_example, resolve_semantic_view
from idp.storage.object_store import S3ObjectStore

_COMMON = """You read a credit case. First come the data the platform already extracted and reconciled across \
documents ([f1], [f2]...); then the text of each document, line by line ([d1:31] = document 1, region 31). The \
documents are in Spanish. Start from the extracted data: it is reliable, and in the text a label and its value are \
often on separate lines. Respect the roles of the extracted data: the Titular is the client; the Asesor is staff of \
the institution, never the client. Write in clear Spanish, for an executive, without technical jargon. Cite in \
`refs` the exact references each statement rests on. Copy names, amounts and dates exactly as they appear. Do not \
state anything that is not in the case and do not invent figures or references."""

_SUMMARY = prompt("lens_summary", _COMMON + """

You are an analyst of the {area} area. {instructions}
Answer with a headline of one or two sentences, 3 to 8 key points with their references, and in `attention` at \
most 4 alerts an analyst must review in THIS case: data that does not match, amounts that do not add up or key data \
that is missing. Do not include generalities that would apply to any case.""", filled=("area", "instructions"))

_PLAYBOOK = prompt("lens_playbook", _COMMON + """

You are a lawyer of the {area} area. Check EACH point of the playbook against the documents and answer one check \
per point (item_key equal to the point's key):
- status: "cumple" (it meets it), "no_cumple" (the document addresses it but not as required), "no_encontrado" \
(the document does not address it) or "dudoso" (it cannot be decided from what it says).
- explanation: why, in one or two simple sentences in Spanish.
- quote: the shortest verbatim quote of the document that shows it, copied as is; null if there is none.
- refs: the references of that quote.
Add a one-sentence headline in Spanish with the overall conclusion.

Playbook:
{playbook}""", filled=("area", "playbook"))


async def lens_documents(settings: Settings, session: AsyncSession, case: Case, lens: LensDefinition) -> list[LensDocument]:
    """The case's logical documents the lens reads, with their text."""
    return await case_documents(settings, session, case, document_types=lens.document_types)


async def case_documents(settings: Settings, session: AsyncSession, case: Case, *, document_types: list[str] | None = None) -> list[LensDocument]:
    """The case's logical documents (of ``document_types``, or all), with their text — for lenses and investigations."""
    documents = await DocumentRepository(session).list_for_case(case.id)
    segmented = {d.parent_document_id for d in documents if d.parent_document_id is not None}
    types = await DocumentTypeRepository(session).load_catalog()
    store = S3ObjectStore(settings)
    parsed_by_file: dict[str, ParsedDocument] = {}
    out: list[LensDocument] = []
    for d in documents:
        if d.id in segmented or d.status == "failed" or (document_types and d.document_type not in document_types):
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
    with traced_llm_call(role="reasoning", model=model_for("reasoning")):
        if lens.kind == "summary":
            return structured(purpose=f"lens/{lens.key}", role="reasoning", output=LensSummaryAnswer,
                              instructions=_SUMMARY.render(area=area, instructions=lens.instructions), task=context)
        playbook = "\n".join(f"- {i.key}: {i.label}" + (f" ({i.guidance})" if i.guidance else "") for i in lens.playbook)
        return structured(purpose=f"lens/{lens.key}", role="reasoning", output=PlaybookAnswer,
                          instructions=_PLAYBOOK.render(area=area, playbook=playbook), task=context)


async def run_lens(settings: Settings, result_id: uuid.UUID) -> None:
    """Its model calls are its own run in aeon, under the service agent's budget (VRT-56)."""
    with charged_to(f"veritium-lens-{result_id}", settings.aeon_service_agent_ref):
        await _run_lens(settings, result_id)


async def _run_lens(settings: Settings, result_id: uuid.UUID) -> None:
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
            result.status, result.model = "done", (resolved_models() or {}).get("reasoning")
        except Exception as exc:
            result.status, result.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        result.finished_at = datetime.now(UTC)
        await session.commit()


# Lens readings started outside a request (MCP, VRT-53): kept so they are not garbage-collected mid-run.
_launched: set[asyncio.Task] = set()


def launch(settings: Settings, result_id: uuid.UUID) -> None:
    task = asyncio.create_task(run_lens(settings, result_id))
    _launched.add(task)
    task.add_done_callback(_launched.discard)
