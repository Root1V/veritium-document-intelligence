"""The discrepancy investigator (VRT-66): for a validation finding, a
bounded synaptum agent looks into it with tools — the evidence of each
source, reading or searching the documents, looking at a region, comparing
names, the employee master — and leaves the reviewer a diagnosis, a likely
cause, a suggested action and the evidence it rests on.

It never decides and never corrects: a suggestion waits for a person, and
what the person did with it (accepted, corrected otherwise, dismissed) is
what tells whether investigating is worth its cost. Its evidence is checked
against the documents' text; a suggested correction that does not point at
a datum actually extracted is turned into "review manually"."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein
from synaptum import Tool, tool
from sqlalchemy.ext.asyncio import AsyncSession
from synaptum.core.errors import ProviderError, SynaptumError

from idp.api.case_outcome import field_evidence
from idp.config import Settings
from idp.domain.lenses import LensDocument
from idp.llm.port import inference, model_for
from idp.llm.prompts import prompt
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, Investigation, ReviewItem, ValidationIssue
from idp.persistence.repositories import CaseRepository, DocumentRepository, ReferenceDataRepository, ReviewRepository
from idp.pipeline.case_evaluation import refresh_verdict
from idp.pipeline.lenses import case_documents
from idp.pipeline.orchestrator import HARDCODED_RULE_DESCRIPTIONS
from idp.tools.catalog import spec
from idp.validation.entity_matching import EntityKind, match_entities, normalize_text

log = logging.getLogger(__name__)

Cause = Literal["error_de_lectura", "dato_de_otro_lugar", "documentos_de_otra_persona", "diferencia_real", "no_esta_en_maestro", "formato", "no_determinado"]
Action = Literal["corregir_dato", "confirmar_dato", "pedir_documento", "revisar_manualmente"]

CAUSE_LABEL = {
    "error_de_lectura": "Error de lectura del documento",
    "dato_de_otro_lugar": "Se tomó otro dato del documento",
    "documentos_de_otra_persona": "Documentos de otra persona",
    "diferencia_real": "Diferencia real entre documentos",
    "no_esta_en_maestro": "No está en el maestro",
    "formato": "Formato distinto",
    "no_determinado": "No se pudo determinar",
}
ACTION_LABEL = {
    "corregir_dato": "Corregir el dato",
    "confirmar_dato": "Confirmar el dato como está",
    "pedir_documento": "Pedir un documento al cliente",
    "revisar_manualmente": "Revisar manualmente",
}


class Cited(BaseModel):
    document: str = Field(description="Referencia del documento: d1, d2…")
    page: int | None = Field(default=None, description="Página, desde 1.")
    text: str = Field(description="El texto del documento que lo muestra, copiado tal cual.")


class InvestigationAnswer(BaseModel):
    diagnosis: str = Field(description="Qué pasa, en 1 a 3 oraciones claras para un revisor no técnico.")
    cause: Cause
    action: Action
    document: str | None = Field(default=None, description="Si action es corregir_dato o confirmar_dato: el documento (d1, d2…).")
    field: str | None = Field(default=None, description="Si action es corregir_dato o confirmar_dato: el campo extraído de ese documento.")
    value: str | None = Field(default=None, description="Si action es corregir_dato: el valor correcto según el documento.")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Cited] = Field(default_factory=list, description="Lo que lo demuestra, con el texto copiado del documento.")


_INSTRUCTIONS = prompt("investigate_finding", """Eres un analista que investiga un hallazgo de validacion en un expediente de credito, \
para dejarle al revisor humano un diagnostico listo. No decides el expediente ni corriges nada: propones, con evidencia.

Hallazgo:
{finding}

Documentos del expediente (usa su referencia d1, d2… en las herramientas y en la respuesta):
{documents}

Datos extraidos del documento del hallazgo:
{fields}

Como investigar:
1. Mira la evidencia del dato en cada documento (get_evidence) y lee o busca en los documentos (read_document, search_document) \
para confirmar que dice realmente cada uno.
2. Si sospechas un error de lectura (digitos o letras parecidas), mira la region (read_region_image).
3. Para nombres usa compare_names; para codigos de empleado, find_employee.
4. Distingue: un error de lectura o un dato tomado de otro lugar (se corrige), documentos que son de otra persona (hay que pedir \
el correcto), una diferencia real entre documentos o un dato que no esta en el maestro (lo decide una persona).
5. Sugiere corregir_dato solo si el documento muestra claramente el valor correcto, y entonces indica document, field (un campo de \
los datos extraidos) y value. Nunca inventes un valor.
6. Cita en evidence el texto exacto del documento. Si no puedes concluir, usa cause no_determinado y action revisar_manualmente.
Responde en español, en lenguaje de negocio.""", filled=("finding", "documents", "fields"))


def _ref(i: int) -> str:
    return f"d{i + 1}"


def _blocks(doc: LensDocument) -> list[Any]:
    if doc.page_start is None:
        return list(doc.parsed.blocks)
    end = doc.page_end if doc.page_end is not None else doc.page_start
    return [b for b in doc.parsed.blocks if doc.page_start <= b.page <= end]


def _line(block: Any) -> str:
    return f"[r{block.region_id} pág.{block.page + 1}] {block.text}"


def _crop_b64(doc: LensDocument, region_id: int) -> str | None:
    block = doc.parsed.block(region_id)
    page_b64 = doc.parsed.page_images_b64.get(block.page) if block else None
    if block is None or page_b64 is None:
        return None
    image = Image.open(io.BytesIO(base64.b64decode(page_b64)))
    width, height = image.size
    x1, y1, x2, y2 = block.bbox
    box = (max(0, int(x1 * width) - 10), max(0, int(y1 * height) - 10), min(width, int(x2 * width) + 10), min(height, int(y2 * height) + 10))
    buf = io.BytesIO()
    image.crop(box).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def investigator_tools(settings: Settings, case: Case, documents: list[LensDocument]) -> list[Tool]:
    """The investigator's tools over one case; descriptions from the tool catalog (VRT-53)."""
    by_ref = {_ref(i): d for i, d in enumerate(documents)}
    factory = get_session_factory(settings)

    def doc(ref: str) -> LensDocument:
        found = by_ref.get(ref.strip().lower())
        if found is None:
            raise ValueError(f"no hay documento {ref}; usa {', '.join(by_ref)}")
        return found

    @tool(idempotent=True, description=spec("get_evidence").description)
    async def get_evidence(attribute: str, role: str = "titular") -> str:
        async with factory() as session:
            fresh = await CaseRepository(session).get(case.id)
            try:
                evidence = await field_evidence(session, fresh, attribute, role)  # type: ignore[arg-type]
            except LookupError as exc:
                return str(exc)
        lines = [f"{evidence.name} del {role}: {evidence.value} ({evidence.agreement})"]
        for s in evidence.sources:
            lines.append(f"- {s.document}: campo {s.field} = {s.value!r}, pág. {s.page}, texto {s.source_text!r}")
        return "\n".join(lines)

    @tool(idempotent=True, description=spec("read_document").description)
    async def read_document(document: str, region_ids: list[int] | None = None, page: int | None = None) -> str:
        d = doc(document)
        blocks = _blocks(d)
        if region_ids:
            wanted = set(region_ids)
            blocks = [b for b in blocks if b.region_id in wanted]
        elif page is not None:
            blocks = [b for b in blocks if b.page + 1 == page]
        text = "\n".join(_line(b) for b in blocks)
        return text[:6000] or "Nada en esa parte del documento."

    @tool(idempotent=True, description=spec("search_document").description)
    async def search_document(document: str, text: str) -> str:
        d = doc(document)
        needle = normalize_text(text)
        scored = [(fuzz.partial_ratio(needle, normalize_text(b.text)), b) for b in _blocks(d) if b.text.strip()]
        hits = [b for score, b in sorted(scored, key=lambda x: -x[0]) if score >= 85][:8]
        return "\n".join(_line(b) for b in hits) or f"No aparece '{text}' en {document}."

    @tool(idempotent=True, description=spec("read_region_image").description)
    async def read_region_image(document: str, region_id: int) -> str:
        crop = await asyncio.to_thread(_crop_b64, doc(document), region_id)
        if crop is None:
            return f"No hay imagen de la región {region_id}."
        return await inference().vision(purpose="investigate_region", image_b64=crop, prompt="Transcribe exactamente el texto de esta imagen, sin interpretar.")

    @tool(idempotent=True, description=spec("compare_names").description)
    async def compare_names(name_a: str, name_b: str) -> str:
        outcome = match_entities(
            EntityKind.PERSON, name_a, name_b, high_threshold=settings.entity_match_high_threshold, low_threshold=settings.entity_match_low_threshold
        )
        verdict = {"match": "la misma persona", "ambiguous": "dudoso", "no_match": "personas distintas"}[outcome.band]
        return f"Similitud {outcome.score:.2f}: {verdict} ({outcome.normalized_a!r} frente a {outcome.normalized_b!r})."

    @tool(idempotent=True, description=spec("find_employee").description)
    async def find_employee(code: str | None = None, name: str | None = None) -> str:
        async with factory() as session:
            repo = ReferenceDataRepository(session)
            if code:
                exact = await repo.find_employee_by_code(code.strip())
                if exact is not None:
                    return f"El código {code} existe: {exact['full_name']} ({'activo' if exact['active'] else 'inactivo'})."
            employees = await repo.list_active_employee_names()
        if code:
            near = sorted(employees, key=lambda e: Levenshtein.distance(e[0], code.strip()))[:3]
            return f"El código {code} no está en el maestro. Los más parecidos: " + "; ".join(f"{c} — {n}" for c, n in near)
        if name:
            near = sorted(employees, key=lambda e: -fuzz.token_set_ratio(normalize_text(name), normalize_text(e[1])))[:3]
            return "Los más parecidos por nombre: " + "; ".join(f"{c} — {n}" for c, n in near)
        return "Indica code o name."

    return [get_evidence, read_document, search_document, read_region_image, compare_names, find_employee]


def _finding_text(issue: ValidationIssue, documents: list[LensDocument]) -> str:
    refs = {d.document_id: _ref(i) for i, d in enumerate(documents)}
    rule = HARDCODED_RULE_DESCRIPTIONS.get(issue.rule_id, issue.rule_id)
    where = refs.get(issue.document_id) if issue.document_id else None
    lines = [f"Regla: {rule}", f"Mensaje: {issue.message}", f"Severidad: {issue.severity}"]
    if where:
        lines.append(f"Documento: {where}")
    if issue.field_path:
        lines.append(f"Dato: {issue.field_path}")
    if issue.expected is not None:
        lines.append(f"Esperado: {json.dumps(issue.expected, ensure_ascii=False)[:600]}")
    if issue.actual is not None:
        lines.append(f"Encontrado: {json.dumps(issue.actual, ensure_ascii=False)[:600]}")
    return "\n".join(lines)


def _fields_of(case: Case, document_id: uuid.UUID | None) -> dict[str, Any]:
    document = next((d for d in case.documents if d.id == document_id), None)
    payload = document.extraction.payload if document is not None and document.extraction is not None else {}
    return {k: v.get("value") for k, v in (payload or {}).items() if isinstance(v, dict) and "value" in v}


def finalize(answer: InvestigationAnswer, documents: list[LensDocument], fields_by_document: dict[uuid.UUID, dict[str, Any]]) -> dict[str, Any]:
    """What is kept of the agent's answer: document references resolved,
    each quote checked against its document's text, and a correction that
    does not point at an extracted datum turned into a manual review."""
    by_ref = {_ref(i): d for i, d in enumerate(documents)}
    target = by_ref.get((answer.document or "").strip().lower())
    action, diagnosis = answer.action, answer.diagnosis.strip()
    field = answer.field.strip() if answer.field else None
    if action in ("corregir_dato", "confirmar_dato"):
        known = fields_by_document.get(target.document_id, {}) if target else {}
        if target is None or field not in known or (action == "corregir_dato" and not (answer.value or "").strip()):
            action, field, target = "revisar_manualmente", None, None
            diagnosis += " (La sugerencia no apuntaba a un dato extraído; queda para revisión manual.)"
    evidence = []
    for cited in answer.evidence:
        d = by_ref.get(cited.document.strip().lower())
        text = " ".join(b.text for b in _blocks(d)) if d else ""
        evidence.append(
            {
                "document_id": str(d.document_id) if d else None,
                "document": d.name if d else cited.document,
                "page": cited.page,
                "text": cited.text,
                "verified": bool(d) and normalize_text(cited.text) in normalize_text(text),
            }
        )
    return {
        "diagnosis": diagnosis,
        "cause": answer.cause,
        "action": action,
        "document_id": target.document_id if target else None,
        "field_path": field,
        "suggested_value": answer.value.strip() if action == "corregir_dato" and answer.value else None,
        "confidence": answer.confidence,
        "evidence": evidence,
    }


async def investigate(settings: Settings, investigation_id: uuid.UUID) -> None:
    factory = get_session_factory(settings)
    async with factory() as session:
        row = await session.get(Investigation, investigation_id)
        if row is None or row.status != "running":
            return
        try:
            case = await CaseRepository(session).get(row.case_id)
            issue = await session.get(ValidationIssue, row.validation_issue_id) if row.validation_issue_id else None
            if case is None or issue is None:
                raise ValueError("el hallazgo ya no existe")
            documents = await case_documents(settings, session, case)
            fields_by_document = {d.document_id: _fields_of(case, d.document_id) for d in documents}
            listed = "\n".join(f"- {_ref(i)}: {d.name}" for i, d in enumerate(documents))
            fields = json.dumps(fields_by_document.get(issue.document_id, {}), ensure_ascii=False)[:3000] if issue.document_id else "(el hallazgo es del expediente)"
            instructions = _INSTRUCTIONS.render(finding=_finding_text(issue, documents), documents=listed, fields=fields)
            tools = investigator_tools(settings, case, documents)
            answer, steps = None, []
            for attempt, temperature in enumerate(_TEMPERATURES):
                try:
                    answer, steps = await inference().run_agent(
                        purpose=f"investigate/{issue.rule_id}", instructions=instructions, task="Investiga el hallazgo y entrega tu conclusión.",
                        tools=tools, output=InvestigationAnswer, max_steps=settings.investigation_max_turns, temperature=temperature,
                    )
                    break
                except ProviderError as exc:
                    # The model sometimes writes a malformed tool call; at temperature 0 the same request fails the same
                    # way, so the retry varies the sampling. Anything else is not the model's format, and is not retried.
                    if attempt == len(_TEMPERATURES) - 1 or not _malformed(exc):
                        raise
                    log.info("investigation %s: tool call malformed (%s); retrying at temperature %s", investigation_id, exc, _TEMPERATURES[attempt + 1])
            if answer is None:
                raise ValueError("el investigador no entregó una conclusión")
            for key, value in finalize(answer, documents, fields_by_document).items():
                setattr(row, key, value)
            if row.action == "corregir_dato" and row.document_id is not None and row.field_path is not None:
                await _queue_for_review(session, case, row.document_id, row.field_path)
            row.trace = [{"tool": s.call.name, "arguments": dict(s.call.arguments)} for s in steps if s.call is not None]
            row.status, row.model = "done", model_for("reasoning")
        except (SynaptumError, ValueError, LookupError) as exc:
            row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        except Exception as exc:  # never leave it "running"
            log.exception("investigation %s failed", investigation_id)
            row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        row.finished_at = datetime.now(UTC)
        await session.commit()


# A malformed tool call from the model is retried once, sampling differently.
_TEMPERATURES = (0.0, 0.4)


def _malformed(error: ProviderError) -> bool:
    text = str(error)
    return error.status == 500 or "Argumentos ilegibles" in text


async def _queue_for_review(session: AsyncSession, case: Case, document_id: uuid.UUID, field_path: str) -> None:
    """A suggested correction is applied by a person, through the review queue,
    with its reason and audit like any other: if the field has no review item,
    one is opened for it (the suggestion shows there), and the verdict follows."""
    review = ReviewRepository(session)
    if await review.has_item_for_field(document_id, field_path):
        return
    document = next((d for d in case.documents if d.id == document_id), None)
    leaf = (document.extraction.payload or {}).get(field_path, {}) if document is not None and document.extraction is not None else {}
    await review.create_item(
        ReviewItem(
            document_id=document_id, field_path=field_path, current_value={"value": leaf.get("value")}, confidence=float(leaf.get("confidence") or 1.0),
            reason="investigation",
        )
    )
    await DocumentRepository(session).mark_needs_review(document_id)
    await refresh_verdict(session, case.id)


_launched: set[asyncio.Task] = set()


def launch(settings: Settings, investigation_ids: list[uuid.UUID]) -> None:
    """Investigate one after another, in the background (on-demand: each costs model calls)."""

    async def run_all() -> None:
        for investigation_id in investigation_ids:
            await investigate(settings, investigation_id)

    task = asyncio.create_task(run_all())
    _launched.add(task)
    task.add_done_callback(_launched.discard)
