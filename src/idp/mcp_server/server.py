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

import json
import re
import uuid
from typing import Any

from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette

from idp.api.case_contract import build_case_result, latest_run
from idp.config import Settings
from idp.domain.case_progress import Progress, progress
from idp.domain.process_profile import ProcessProfileDefinition
from idp.events import inbound
from idp.events.inbound import DocumentRef
from idp.mcp_server.auth import VeritiumTokenVerifier, caller, quota, require_role
from idp.mcp_server.tasks import CaseRunTasks
from idp.api.case_outcome import VERDICT_LABEL, CaseOutcome, case_outcome
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case
from idp.persistence.repositories import CaseRepository, DocumentTypeRepository, ProcessProfileRepository

INSTRUCTIONS = """Veritium revisa los documentos de un expediente (préstamos, convenios y otros procesos) y responde \
qué debe hacer el proceso: continuar, revisión humana o devolver al cliente, con los motivos.
1. list_processes: qué pide cada proceso.
2. submit_case: abre el expediente con sus documentos (por referencia: s3:// o https:// de un origen autorizado).
3. El procesamiento toma minutos: sigue la tarea (tasks/get) o consulta get_case_status / get_case_result.
4. Si faltan documentos, add_documents al mismo expediente.
Usa request_id al crear o agregar: repetir la llamada con el mismo request_id no duplica nada."""

_WRITERS = ("integracion", "operador", "admin")


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
    process: str | None
    status: str
    verdict_label: str | None
    created_at: str


_STATE = {"done": "listo", "running": "en curso", "pending": "pendiente", "failed": "con error"}


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
        claims = require_role(*_WRITERS)
        source = f"mcp/{claims.get('api_client_id') or claims['name']}"
        answer = await inbound.handle(settings, {"specversion": "1.0", "id": request_id or uuid.uuid4().hex, "source": source, "type": type_, "data": data})
        if not answer.accepted or answer.case_id is None:
            raise ToolError(answer.reason or "no se pudo")
        async with factory() as session:
            return await case_outcome(session, await _case(session, str(answer.case_id)))

    @mcp.tool(title="Procesos disponibles", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    async def list_processes() -> list[ProcessInfo]:
        """Los procesos que Veritium sabe revisar y qué documentos pide cada uno."""
        caller()
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

    @mcp.tool(title="Abrir un expediente", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
    async def submit_case(
        profile: str,
        documents: list[DocumentRef],
        external_ref: str | None = None,
        process_data: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> CaseOutcome:
        """Abre un expediente bajo un proceso (`profile`, de list_processes) con sus documentos por referencia
        (`documents[].url`: s3:// o https:// de un origen autorizado). `external_ref` es tu identificador;
        `request_id` hace la llamada repetible sin duplicar. Responde enseguida; el veredicto llega en minutos."""
        data = {"profile": profile, "external_ref": external_ref, "process_data": process_data, "documents": [d.model_dump() for d in documents]}
        return await _command(inbound.SUBMIT, data, request_id)

    @mcp.tool(title="Agregar documentos", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
    async def add_documents(documents: list[DocumentRef], case_id: str | None = None, external_ref: str | None = None, request_id: str | None = None) -> CaseOutcome:
        """Agrega documentos a un expediente (por `case_id` o por tu `external_ref`) y lo vuelve a revisar."""
        data = {"case_id": case_id, "external_ref": external_ref, "documents": [d.model_dump() for d in documents]}
        return await _command(inbound.ADD_DOCUMENTS, data, request_id)

    @mcp.tool(title="Estado del expediente", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    async def get_case_status(case_id: str) -> CaseStatus:
        """En qué etapa va el expediente: recibido, lectura, clasificación, extracción, validación, decisión."""
        caller()
        async with factory() as session:
            case = await _case(session, case_id)
            outcome = await case_outcome(session, case)
            p = _progress(case)
            steps = [f"{s.label}: {_STATE[s.state]}" + (f" ({s.done} de {s.total})" if s.total else "") for s in p.steps]
            return CaseStatus(case_id=case.id, external_ref=case.external_ref, status=p.status_label, now=p.current, steps=steps, verdict_label=outcome.verdict_label)

    @mcp.tool(title="Resultado del expediente", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    async def get_case_result(case_id: str) -> CaseOutcome:
        """El veredicto (continuar, revisión humana o devolver al cliente), sus motivos, lo que falta y los documentos.
        El detalle completo, con la evidencia de cada dato, está en el recurso `result_uri`."""
        caller()
        async with factory() as session:
            return await case_outcome(session, await _case(session, case_id))

    @mcp.tool(title="Buscar expedientes", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    async def find_cases(external_ref: str | None = None, limit: int = 10) -> list[CaseItem]:
        """Expedientes por tu `external_ref`, o los más recientes."""
        caller()
        async with factory() as session:
            cases = await CaseRepository(session).list(external_ref=external_ref, limit=max(1, min(limit, 50)))
            return [
                CaseItem(
                    case_id=c.id, external_ref=c.external_ref, process=c.profile_version.profile.name if c.profile_version else None,
                    status=_progress(c).status_label, verdict_label=VERDICT_LABEL.get(c.verdict or ""), created_at=c.created_at.isoformat(),
                )
                for c in cases
            ]

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

