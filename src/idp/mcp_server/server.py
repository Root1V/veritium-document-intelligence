"""Veritium's MCP server (VRT-51, spec 2026-07-28): what an agent needs to
use Veritium as a tool — learn what each process asks for, open a case with
its documents, add what was missing, follow it and read its verdict.

Streamable HTTP at ``/mcp`` inside the API process, stateless (any instance
answers any request). Same identities as the REST API: a person's login
token or a connected system's client credentials (``POST /auth/token``),
with the same roles and quota. Opening a case and adding documents go
through the same command handling as the event bus (events/inbound.py):
documents by claim-check, and a repeated ``request_id`` does nothing twice.
Long work is a task (tasks.py) for clients that support it."""

from __future__ import annotations

import functools
import json
import re
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from fastapi import HTTPException
from pydantic import AnyHttpUrl, BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette

from idp.api.case_contract import build_case_result, latest_run
from idp.config import Settings
from idp.domain.case_progress import CASE_STATUS, Progress, progress
from idp.domain.process_profile import ProcessProfileDefinition
from idp.events import inbound
from idp.domain.lenses import LensOutput
from idp.events.claim_check import ClaimCheckError, fetch
from idp.events.inbound import DocumentRef
from idp.mcp_server.auth import VeritiumTokenVerifier, caller, quota
from idp.mcp_server.tasks import CaseRunTasks
from idp.api.case_outcome import VERDICT_LABEL, CaseOutcome, FieldEvidence, case_outcome, field_evidence
from idp.api.routes.review import list_pending_review
from idp.api.routes.upload_sessions import SessionRequest, create_session
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, LensResult
from idp.persistence.repositories import CaseRepository, DocumentTypeRepository, LensRepository, ProcessProfileRepository
from idp.pipeline.lenses import launch
from idp.pipeline.quick_check import check_file
from idp.tools.catalog import ToolSpec, exposed

INSTRUCTIONS = """Veritium revisa los documentos de un expediente (préstamos, convenios y otros procesos) y responde \
qué debe hacer el proceso: continuar, revisión humana o devolver al cliente, con los motivos.
1. list_processes: qué pide cada proceso.
2. Si los documentos los tiene una persona: request_documents_link le da un enlace para subirlos desde el teléfono.
   Si los tienes tú: quick_check_document revisa cada archivo en segundos y submit_case abre el expediente
   (documentos por referencia: s3:// o https:// de un origen autorizado).
3. El procesamiento toma minutos: sigue la tarea (tasks/get) o consulta get_case_status / get_case_result.
4. Si faltan documentos, add_documents al mismo expediente.
5. Para explicar: get_field_evidence dice de dónde sale un dato; read_with_lens da la lectura de Riesgos o Legal.
Usa request_id al crear o agregar: repetir la llamada con el mismo request_id no duplica nada."""



class Requirement(BaseModel):
    label: str
    required: bool
    condition: str | None = Field(default=None, description="Cuándo aplica (expresión sobre los datos del proceso); sin condición, siempre.")
    accepted_documents: list[str] = Field(description="Tipos de documento que lo cumplen; vacío = cualquiera que aporte el dato.")


class ProcessInfo(BaseModel):
    key: str = Field(description="Lo que se pasa como `profile` en submit_case.")
    name: str
    description: str | None
    version: int
    requirements: list[Requirement]
    process_data: list[str] = Field(description="Datos del proceso que sus condiciones leen (van en `process_data`).")


class CaseStatus(BaseModel):
    case_id: uuid.UUID
    external_ref: str | None
    status: str
    now: str = Field(description="Qué está pasando ahora.")
    steps: list[str] = Field(description="Cada etapa con su estado: listo, en curso, pendiente o con error.")
    verdict_label: str | None


class CaseItem(BaseModel):
    case_id: uuid.UUID
    external_ref: str | None
    name: str = Field(description="Cómo nombrarlo ante una persona: su external_ref, o el inicio de su id si no tiene.")
    process: str | None
    status: str
    verdict_label: str | None
    documents: list[str] = Field(description="Sus documentos, por tipo (o nombre de archivo si no se clasificó).")
    created_at: str


class CaseList(BaseModel):
    summary: str = Field(description="Los números en una frase, listos para leer.")
    total: int = Field(description="Cuántos expedientes cumplen el filtro, aunque se muestren menos.")
    cases: list[CaseItem]


class CaseRef(BaseModel):
    case_id: uuid.UUID
    name: str
    verdict_label: str | None


class CasesOverview(BaseModel):
    summary: str = Field(description="Los números en una frase, listos para leer.")
    period: str
    total: int
    by_verdict: dict[str, int] = Field(description="Cuántos por veredicto; 'Sin veredicto todavía' para los que siguen en proceso.")
    by_status: dict[str, int]
    needs_action: list[CaseRef] = Field(description="Hasta 10 que necesitan acción: primero los de devolver al cliente, luego los de revisión humana.")


class PendingReview(BaseModel):
    case_id: uuid.UUID
    case_ref: str | None
    document: str
    field: str
    value: Any = Field(description="El valor leído hoy.")
    why: str = Field(description="Por qué espera revisión.")
    suggestion: str | None = Field(default=None, description="Lo que sugiere el investigador de discrepancias, si lo investigó.")


class ReviewQueue(BaseModel):
    summary: str = Field(description="Los números en una frase, listos para leer.")
    total: int = Field(description="Cuántos datos (no expedientes) esperan revisión, aunque se muestren menos.")
    cases: int = Field(description="En cuántos expedientes distintos están esos datos.")
    by_why: dict[str, int] = Field(description="Cuántos esperan por cada motivo, contando todos.")
    items: list[PendingReview]

Verdict = Literal["continue", "human_review", "return_to_client"]
CaseState = Literal["submitted", "uploaded", "processing", "completed", "failed"]
Day = Annotated[str | None, Field(description="Fecha AAAA-MM-DD en el calendario del negocio, inclusive.")]

_STATE = {"done": "listo", "running": "en curso", "pending": "pendiente", "failed": "con error"}
_REVIEW_REASON = {"low_confidence": "confianza baja", "validation_issue": "problema de validación", "investigation": "sugerencia del investigador"}
_FILE_VERDICT = {"ok": "se puede leer", "warning": "se puede leer, con observaciones", "reject": "no se puede leer"}
_LENS_KIND = {"summary": "resumen", "playbook": "revisión de cláusulas"}


class DocumentsLink(BaseModel):
    upload_url: str = Field(description="El enlace a enviar a la persona.")
    expires_at: str
    session_id: uuid.UUID


class FileCheck(BaseModel):
    verdict: str
    observations: list[str]
    detected_type: str | None = Field(description="Tipo reconocido en el catálogo, 'otro', o vacío si no se pudo.")
    detected_type_name: str | None
    pages: int


class LensInfo(BaseModel):
    key: str
    name: str
    area: str
    kind: str
    description: str


class LensReading(BaseModel):
    lens: str
    status: Literal["en curso", "lista"]
    reading: LensOutput | None = None
    note: str | None = None


def _guarded(tool: ToolSpec, fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Who may call it comes from the catalog, in one place."""

    @functools.wraps(fn)
    async def call(*args: Any, **kwargs: Any) -> Any:
        role = caller()["role"]
        if role not in tool.roles:
            raise ToolError(f"tu rol ({role}) no permite usar {tool.title.lower()}; se requiere {' o '.join(tool.roles)}")
        return await fn(*args, **kwargs)

    return call


def _progress(case: Case) -> Progress:
    run = latest_run(case)
    return progress(case.status, run.status if run else None, [d.status for d in case.documents])


async def _case(session: AsyncSession, case_id: str) -> Case:
    try:
        case = await CaseRepository(session).get(uuid.UUID(case_id))
    except ValueError:
        case = None
    if case is None:
        raise ToolError(f"no existe el expediente {case_id}")
    return case


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _name(case: Case) -> str:
    """How a person calls a case: its own reference, or the start of its id."""
    return case.external_ref or f"Expediente {str(case.id)[:8]}"


def _days(settings: Settings, received_from: str | None, received_to: str | None) -> tuple[datetime | None, datetime | None]:
    """[start, end) in the business's calendar for the days given, inclusive."""
    zone = ZoneInfo(settings.business_timezone)
    try:
        first = date.fromisoformat(received_from) if received_from else None
        last = date.fromisoformat(received_to) if received_to else None
    except ValueError as exc:
        raise ToolError(f"fecha inválida ({exc}); usa AAAA-MM-DD") from exc
    start = datetime.combine(first, time.min, zone) if first else None
    end = datetime.combine(last + timedelta(days=1), time.min, zone) if last else None
    return start, end


def build(settings: Settings) -> MCPServer:
    base = settings.public_api_base_url.rstrip("/")
    resource = f"{base}/mcp"
    factory = get_session_factory(settings)
    mcp = MCPServer(
        name="veritium",
        title="Veritium",
        description="Decisión documental: revisa los documentos de un expediente y dice qué debe hacer el proceso, con evidencia.",
        instructions=INSTRUCTIONS,
        version="1.0.0",
        token_verifier=VeritiumTokenVerifier(settings, resource),
        # Our tokens carry no audience: the verifier stamps the resource itself.
        auth=AuthSettings(issuer_url=AnyHttpUrl(base), resource_server_url=AnyHttpUrl(resource), validate_token_resource=False),
        extensions=[CaseRunTasks(settings)],
        # The tool and resource lists change only with a deploy.
        cache_hints={"tools/list": CacheHint(ttl_ms=300_000, scope="public"), "resources/templates/list": CacheHint(ttl_ms=300_000, scope="public")},
        middleware=[quota(settings)],
    )

    async def _command(type_: str, data: dict[str, Any], request_id: str | None) -> CaseOutcome:
        claims = caller()
        source = f"mcp/{claims.get('api_client_id') or claims['name']}"
        answer = await inbound.handle(settings, {"specversion": "1.0", "id": request_id or uuid.uuid4().hex, "source": source, "type": type_, "data": data})
        if not answer.accepted or answer.case_id is None:
            raise ToolError(answer.reason or "no se pudo")
        async with factory() as session:
            return await case_outcome(session, await _case(session, str(answer.case_id)))

    async def list_processes() -> list[ProcessInfo]:
        async with factory() as session:
            catalog = await DocumentTypeRepository(session).load_catalog()
            names = {key: current[1].display_name for key in catalog.keys() if (current := catalog.current(key))}
            out = []
            for profile in await ProcessProfileRepository(session).list_profiles():
                version = ProcessProfileRepository.latest_published(profile)
                if version is None or profile.key == "ad-hoc":
                    continue
                definition = ProcessProfileDefinition.model_validate(version.definition)
                requirements = [
                    Requirement(
                        label=item.label, required=item.required, condition=item.required_when_cel,
                        accepted_documents=[names.get(t, t) for t in ([item.document_type] if item.document_type else item.accepted_document_types or [])],
                    )
                    for item in definition.checklist
                ]
                fields = sorted(set(re.findall(r"\brequest\.([A-Za-z_]\w*)", json.dumps(version.definition))))
                out.append(ProcessInfo(key=profile.key, name=profile.name, description=profile.description, version=version.version, requirements=requirements, process_data=fields))
            return out

    async def submit_case(
        profile: str, documents: list[DocumentRef], external_ref: str | None = None, process_data: dict[str, Any] | None = None, request_id: str | None = None
    ) -> CaseOutcome:
        data = {"profile": profile, "external_ref": external_ref, "process_data": process_data, "documents": [d.model_dump() for d in documents]}
        return await _command(inbound.SUBMIT, data, request_id)

    async def add_documents(documents: list[DocumentRef], case_id: str | None = None, external_ref: str | None = None, request_id: str | None = None) -> CaseOutcome:
        data = {"case_id": case_id, "external_ref": external_ref, "documents": [d.model_dump() for d in documents]}
        return await _command(inbound.ADD_DOCUMENTS, data, request_id)

    async def get_case_status(case_id: str) -> CaseStatus:
        async with factory() as session:
            case = await _case(session, case_id)
            outcome = await case_outcome(session, case)
            p = _progress(case)
            steps = [f"{s.label}: {_STATE[s.state]}" + (f" ({s.done} de {s.total})" if s.total else "") for s in p.steps]
            return CaseStatus(case_id=case.id, external_ref=case.external_ref, status=p.status_label, now=p.current, steps=steps, verdict_label=outcome.verdict_label)

    async def get_case_result(case_id: str) -> CaseOutcome:
        async with factory() as session:
            return await case_outcome(session, await _case(session, case_id))

    zone = ZoneInfo(settings.business_timezone)

    async def find_cases(
        external_ref: str | None = None, received_from: Day = None, received_to: Day = None, verdict: Verdict | None = None,
        status: CaseState | None = None, process: Annotated[str | None, Field(description="`key` del proceso (list_processes).")] = None, limit: int = 10,
    ) -> CaseList:
        start, end = _days(settings, received_from, received_to)
        filters = {"created_from": start, "created_to": end, "verdict": verdict, "status": status, "profile_key": process}
        async with factory() as session:
            repo = CaseRepository(session)
            cases = await repo.list(external_ref=external_ref, **filters, limit=max(1, min(limit, 50)))
            total = await repo.count(external_ref=external_ref, **filters)
            catalog = await DocumentTypeRepository(session).load_catalog()
        names = {key: current[1].display_name for key in catalog.keys() if (current := catalog.current(key))}
        return CaseList(
            summary=f"{_count(total, 'expediente cumple', 'expedientes cumplen')} el filtro" + (f"; se muestran los {len(cases)} más recientes." if len(cases) < total else "."),
            total=total,
            cases=[
                CaseItem(
                    case_id=c.id, external_ref=c.external_ref, name=_name(c),
                    process=c.profile_version.profile.name if c.profile_version else None, status=_progress(c).status_label,
                    verdict_label=VERDICT_LABEL.get(c.verdict or ""),
                    documents=[names.get(d.document_type or "", d.original_filename) for d in c.documents if d.status != "segmented"],
                    created_at=c.created_at.astimezone(zone).isoformat(),
                )
                for c in cases
            ],
        )

    async def cases_overview(received_from: Day = None, received_to: Day = None, process: str | None = None) -> CasesOverview:
        start, end = _days(settings, received_from, received_to)
        async with factory() as session:
            repo = CaseRepository(session)
            counts = await repo.counts(created_from=start, created_to=end, profile_key=process)
            flagged = [
                c for verdict in ("return_to_client", "human_review")
                for c in await repo.list(created_from=start, created_to=end, profile_key=process, verdict=verdict, limit=10)
            ][:10]
        by_verdict: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for verdict, status, n in counts:
            label = VERDICT_LABEL.get(verdict or "", "Sin veredicto todavía")
            by_verdict[label] = by_verdict.get(label, 0) + n
            by_status[CASE_STATUS.get(status, status)] = by_status.get(CASE_STATUS.get(status, status), 0) + n
        period = f"{received_from or 'inicio'} al {received_to or 'hoy'}"
        needs_action = [CaseRef(case_id=c.id, name=_name(c), verdict_label=VERDICT_LABEL.get(c.verdict or "")) for c in flagged]
        total = sum(by_verdict.values())
        acting = sum(n for label, n in by_verdict.items() if label in (VERDICT_LABEL["return_to_client"], VERDICT_LABEL["human_review"]))
        summary = f"Del {period} llegaron {_count(total, 'expediente', 'expedientes')}"
        summary += (": " + ", ".join(f"{n} {label.lower()}" for label, n in by_verdict.items()) + "." if total else ".")
        if acting > len(needs_action):
            summary += f" Necesitan acción {acting}; se nombran {len(needs_action)}."
        return CasesOverview(summary=summary, period=period, total=total, by_verdict=by_verdict, by_status=by_status, needs_action=needs_action)

    async def get_review_queue(case_id: str | None = None, limit: int = 20) -> ReviewQueue:
        async with factory() as session:
            if case_id is not None:
                case_id = str((await _case(session, case_id)).id)
            items = [i for i in await list_pending_review(session) if case_id is None or str(i.case_id) == case_id]
        pending = [
            PendingReview(
                case_id=i.case_id, case_ref=i.case_ref, document=i.document_type_name or i.filename, field=i.label, value=i.current_value.get("value"),
                why=i.finding or _REVIEW_REASON.get(i.reason, i.reason),
                suggestion=f"{i.suggestion.action_label}: {i.suggestion.value} — {i.suggestion.diagnosis}" if i.suggestion else None,
            )
            for i in items
        ]
        cases = len({p.case_id for p in pending})
        summary = f"{_count(len(pending), 'dato espera', 'datos esperan')} revisión en {_count(cases, 'expediente', 'expedientes')}."
        return ReviewQueue(summary=summary, total=len(pending), cases=cases, by_why=dict(Counter(p.why for p in pending).most_common()), items=pending[: max(1, min(limit, 50))])

    async def request_documents_link(
        profile: str | None = None, case_id: str | None = None, external_ref: str | None = None, process_data: dict[str, Any] | None = None,
        minutes: int | None = None,
    ) -> DocumentsLink:
        if not profile and not case_id:
            raise ToolError("indica el proceso (`profile`) para un expediente nuevo o `case_id` para completar uno")
        try:
            body = SessionRequest(profile=profile or "", case_id=uuid.UUID(case_id) if case_id else None, external_ref=external_ref, process_data=process_data, minutes=minutes)
            async with factory() as session:
                created = await create_session(session, settings, body, created_by=caller()["name"])
        except (ValueError, ValidationError) as exc:
            raise ToolError(f"datos inválidos: {exc}") from exc
        except HTTPException as exc:
            raise ToolError(str(exc.detail)) from exc
        return DocumentsLink(upload_url=created.upload_url, expires_at=created.expires_at.isoformat(), session_id=created.id)

    async def quick_check_document(url: str, expected_type: str | None = None) -> FileCheck:
        try:
            data = await fetch(settings, url)
        except ClaimCheckError as exc:
            raise ToolError(str(exc)) from exc
        async with factory() as session:
            checked = await check_file(settings, session, data, expected_type=expected_type)
        return FileCheck(
            verdict=_FILE_VERDICT[checked.verdict], observations=[c.message for c in checked.checks], detected_type=checked.detected_type,
            detected_type_name=checked.detected_type_name, pages=checked.facts.page_count,
        )

    async def get_field_evidence(case_id: str, attribute: str, role: str = "titular") -> FieldEvidence:
        async with factory() as session:
            try:
                return await field_evidence(session, await _case(session, case_id), attribute, role)
            except LookupError as exc:
                raise ToolError(str(exc)) from exc

    async def list_lenses() -> list[LensInfo]:
        async with factory() as session:
            return [LensInfo(key=lens.key, name=lens.name, area=lens.area, kind=_LENS_KIND[lens.kind], description=lens.description) for lens in await LensRepository(session).list_lenses()]

    async def read_with_lens(case_id: str, lens_key: str) -> LensReading:
        async with factory() as session:
            case = await _case(session, case_id)
            repo = LensRepository(session)
            lens = await repo.get(lens_key)
            if lens is None:
                raise ToolError(f"no existe la lente '{lens_key}' (ver list_lenses)")
            latest = next((r for r in await repo.results_for_case(case.id) if r.lens_key == lens_key), None)
            current = latest is not None and latest.definition == lens.model_dump(mode="json")
            if latest is not None and latest.status == "running":
                return LensReading(lens=lens.name, status="en curso")
            if latest is not None and latest.status == "done" and current:
                return LensReading(lens=lens.name, status="lista", reading=LensOutput.model_validate(latest.output))
            row = LensResult(case_id=case.id, lens_key=lens_key, definition=lens.model_dump(mode="json"), created_by=caller()["name"])
            session.add(row)
            await session.commit()
            launch(settings, row.id)
            note = f" (la anterior falló: {latest.error})" if latest is not None and latest.status == "failed" else ""
            return LensReading(lens=lens.name, status="en curso", note=f"Lectura iniciada{note}; vuelve a llamar en alrededor de un minuto.")

    tools: dict[str, Callable[..., Any]] = {
        "list_processes": list_processes, "submit_case": submit_case, "add_documents": add_documents, "get_case_status": get_case_status,
        "get_case_result": get_case_result, "find_cases": find_cases, "cases_overview": cases_overview, "get_review_queue": get_review_queue,
        "request_documents_link": request_documents_link,
        "quick_check_document": quick_check_document, "get_field_evidence": get_field_evidence, "list_lenses": list_lenses, "read_with_lens": read_with_lens,
    }
    # The catalog decides what is exposed, how it is described and who may call it (VRT-53).
    assert tools.keys() == {s.name for s in exposed()}, "el catálogo de tools y el servidor MCP no coinciden"
    for s in exposed():
        mcp.add_tool(
            _guarded(s, tools[s.name]), name=s.name, title=s.title, description=s.description,
            annotations=ToolAnnotations(title=s.title, read_only_hint=s.read_only, destructive_hint=False, idempotent_hint=s.idempotent, open_world_hint=False),
        )

    @mcp.resource("veritium://cases/{case_id}/result", title="Resultado completo del expediente", mime_type="application/json")
    async def case_result(case_id: str) -> str:
        """El contrato de resultado v1: veredicto, condiciones, entidades consolidadas con la evidencia por fuente, documentos y hallazgos."""
        caller()
        async with factory() as session:
            try:
                case = await _case(session, case_id)
            except ToolError as exc:
                raise ResourceNotFoundError(str(exc)) from exc
            return (await build_case_result(session, case)).model_dump_json()

    return mcp


def app(mcp: MCPServer, settings: Settings) -> Starlette:
    """The ASGI app: ``/mcp`` plus its protected-resource metadata (RFC 9728)."""
    return mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=settings.mcp_allowed_hosts, allowed_origins=[]),
    )

