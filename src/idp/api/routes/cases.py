"""Case API v1 (VRT-25) — how business processes use Veritium.

POST /v1/cases                      submit a case under a process profile (202; Idempotency-Key)
POST /v1/cases/{id}/documents       add documents to an open case → new run (202)
POST /v1/cases/{id}/reprocess       redo a case, document, rule or attribute → new run (202; VRT-40)
GET  /v1/cases                      list (filter by external_ref)
GET  /v1/cases/{id}                 status, documents, runs
GET  /v1/cases/{id}/result          the result contract v1 (api/case_contract.py)

Processing is asynchronous: the caller polls the status URL (webhooks arrive
in VRT-28). Submitting is open to integracion/operador/admin; reading to any
authenticated user."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.case_contract import CaseResultV1, ConditionResult, ProfileRef, Verdict, build_case_result, condition_result, latest_run, profile_ref
from idp.api.case_service import dispatch_run, open_reprocess_run, open_run, read_uploads, request_fingerprint, resolve_profile_version, store_uploads
from idp.api.deps import get_app_settings, get_current_user, get_db_session, get_object_store, require_role
from idp.config import Settings
from idp.domain.reprocess import ReprocessScope
from idp.domain.verdict import VerdictReason
from idp.persistence.models import Case, User
from idp.persistence.repositories import CaseConditionRepository, CaseRepository, CaseRunRepository
from idp.pipeline.case_evaluation import refresh_verdict
from idp.storage.object_store import S3ObjectStore

router = APIRouter(prefix="/v1/cases", tags=["cases"], dependencies=[Depends(get_current_user)])

Channel = Literal["online", "backoffice", "bulk"]
_TENANT = "default"  # multi-tenant arrives with VRT-57


class CaseLinks(BaseModel):
    self: str
    result: str


class CaseAccepted(BaseModel):
    case_id: uuid.UUID
    run_number: int
    status: str
    # True when this response replays an earlier submission with the same
    # Idempotency-Key and the same content — nothing new was processed.
    replayed: bool
    links: CaseLinks


class DocumentBrief(BaseModel):
    id: uuid.UUID
    filename: str
    document_type: str | None
    status: str
    needs_review: bool
    parent_document_id: uuid.UUID | None


class RunBrief(BaseModel):
    run_number: int
    trigger: str
    scope: dict | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None


class CaseSummary(BaseModel):
    id: uuid.UUID
    external_ref: str | None
    channel: str
    status: str
    profile: ProfileRef | None
    verdict: str | None
    created_at: datetime
    documents: list[DocumentBrief]
    runs: list[RunBrief]
    links: CaseLinks


class CaseListItem(BaseModel):
    id: uuid.UUID
    external_ref: str | None
    channel: str
    status: str
    profile: ProfileRef | None
    verdict: str | None
    created_at: datetime


def _links(case_id: uuid.UUID) -> CaseLinks:
    return CaseLinks(self=f"/v1/cases/{case_id}", result=f"/v1/cases/{case_id}/result")


def _accepted(case: Case, run_number: int, *, replayed: bool) -> CaseAccepted:
    return CaseAccepted(case_id=case.id, run_number=run_number, status=case.status, replayed=replayed, links=_links(case.id))


def _parse_process_data(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"process_data no es JSON válido: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="process_data debe ser un objeto JSON")
    return data


async def _case_or_404(session: AsyncSession, case_id: uuid.UUID) -> Case:
    case = await CaseRepository(session).get(case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return case


def _replay_or_conflict(existing: Case, fingerprint: str) -> CaseAccepted:
    if existing.idempotency_fingerprint != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key ya usada con una solicitud distinta (otro perfil, datos o archivos)",
        )
    run = latest_run(existing)
    return _accepted(existing, run.run_number if run else 0, replayed=True)


@router.post(
    "",
    response_model=CaseAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role("integracion", "operador", "admin"))],
)
async def submit_case(
    background_tasks: BackgroundTasks,
    profile: Annotated[str, Form(description="Clave del perfil de proceso, p. ej. 'convenios'.")],
    files: Annotated[list[UploadFile], File(description="Documentos del expediente.")],
    profile_version: Annotated[int | None, Form(description="Versión publicada; por defecto la última.")] = None,
    external_ref: Annotated[str | None, Form(description="Identificador del expediente en el sistema que llama.")] = None,
    channel: Annotated[Channel, Form()] = "backoffice",
    process_data: Annotated[str | None, Form(description="JSON con los datos del proceso (lo que leen `request` y las reglas request_input).")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=256)] = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    object_store: S3ObjectStore = Depends(get_object_store),
) -> CaseAccepted:
    data = _parse_process_data(process_data)
    uploads = await read_uploads(files)
    if not uploads:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="el expediente debe traer al menos un documento")
    fingerprint = request_fingerprint(
        profile_key=profile, profile_version=profile_version, external_ref=external_ref, channel=channel, process_data=data, uploads=uploads
    )

    repo = CaseRepository(session)
    if idempotency_key is not None:
        existing = await repo.get_by_idempotency_key(tenant=_TENANT, idempotency_key=idempotency_key)
        if existing is not None:
            return _replay_or_conflict(existing, fingerprint)

    version = await resolve_profile_version(session, profile, profile_version)
    try:
        case = await repo.create(
            tenant=_TENANT,
            request_input_payload=data,
            profile_version_id=version.id,
            external_ref=external_ref,
            channel=channel,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint if idempotency_key else None,
        )
    except IntegrityError:
        # Two concurrent submissions with the same key: the other one won.
        await session.rollback()
        existing = await repo.get_by_idempotency_key(tenant=_TENANT, idempotency_key=idempotency_key or "")
        if existing is None:
            raise
        return _replay_or_conflict(existing, fingerprint)

    await store_uploads(session, object_store, case, uploads)
    run = await open_run(session, case, trigger="submit")
    await session.commit()
    await dispatch_run(session, settings, case, run, background_tasks)
    return _accepted(case, run.run_number, replayed=False)


@router.post(
    "/{case_id}/documents",
    response_model=CaseAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role("integracion", "operador", "admin"))],
)
async def add_documents(
    case_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File()],
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    object_store: S3ObjectStore = Depends(get_object_store),
) -> CaseAccepted:
    case = await _case_or_404(session, case_id)
    if await CaseRunRepository(session).has_active_run(case_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="el expediente tiene una corrida en curso; reintentar cuando termine")
    uploads = await read_uploads(files)
    if not uploads:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="no se recibió ningún documento")
    await store_uploads(session, object_store, case, uploads)
    run = await open_run(session, case, trigger="documents_added")
    # Pending work again: a poller must not read the previous run's
    # "completed" while this run waits to start.
    case.status = "uploaded"
    await session.commit()
    await dispatch_run(session, settings, case, run, background_tasks)
    return _accepted(case, run.run_number, replayed=False)


@router.post(
    "/{case_id}/reprocess",
    response_model=CaseAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role("integracion", "operador", "admin"))],
)
async def reprocess_case(
    case_id: uuid.UUID,
    scope: ReprocessScope,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> CaseAccepted:
    """A case or a document is re-extracted and the case re-evaluated; a
    rule or an attribute re-evaluates only the rules it reaches."""
    case = await _case_or_404(session, case_id)
    if await CaseRunRepository(session).has_active_run(case_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="el expediente tiene una corrida en curso; reintentar cuando termine")
    run = await open_reprocess_run(session, settings, case, scope, trigger="reprocess")
    await session.commit()
    await dispatch_run(session, settings, case, run, background_tasks)
    return _accepted(case, run.run_number, replayed=False)


@router.get("", response_model=list[CaseListItem])
async def list_cases(
    external_ref: str | None = None, limit: int = 50, offset: int = 0, session: AsyncSession = Depends(get_db_session)
) -> list[CaseListItem]:
    cases = await CaseRepository(session).list(external_ref=external_ref, limit=min(limit, 200), offset=offset)
    return [
        CaseListItem(
            id=c.id, external_ref=c.external_ref, channel=c.channel, status=c.status, profile=profile_ref(c), verdict=c.verdict, created_at=c.created_at
        )
        for c in cases
    ]


@router.get("/{case_id}", response_model=CaseSummary)
async def get_case(case_id: uuid.UUID, response: Response, session: AsyncSession = Depends(get_db_session)) -> CaseSummary:
    case = await _case_or_404(session, case_id)
    if case.status in ("uploaded", "processing"):
        response.headers["Retry-After"] = "5"
    return CaseSummary(
        id=case.id,
        external_ref=case.external_ref,
        channel=case.channel,
        status=case.status,
        profile=profile_ref(case),
        verdict=case.verdict,
        created_at=case.created_at,
        documents=[
            DocumentBrief(
                id=d.id, filename=d.original_filename, document_type=d.document_type, status=d.status, needs_review=d.needs_review, parent_document_id=d.parent_document_id
            )
            for d in sorted(case.documents, key=lambda d: d.created_at)
        ],
        runs=[RunBrief(run_number=r.run_number, trigger=r.trigger, scope=r.scope, status=r.status, started_at=r.started_at, finished_at=r.finished_at) for r in case.runs],
        links=_links(case.id),
    )


@router.get("/{case_id}/result", response_model=CaseResultV1)
async def get_case_result(case_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> CaseResultV1:
    return await build_case_result(session, await _case_or_404(session, case_id))


class WaiveRequest(BaseModel):
    reason: str = Field(min_length=3, description="Por qué se dispensa el requisito; queda auditado.")


class WaiveResponse(BaseModel):
    condition: ConditionResult
    verdict: Verdict


@router.post(
    "/{case_id}/conditions/{condition_id}/waive",
    response_model=WaiveResponse,
)
async def waive_condition(
    case_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: WaiveRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operador", "admin")),
) -> WaiveResponse:
    """Dispense an open requirement (e.g. the client already proved it by
    other means). Recomputes the verdict immediately, without a new run."""
    repo = CaseConditionRepository(session)
    condition = await repo.get(condition_id)
    if condition is None or condition.case_id != case_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="condition not found")
    if condition.status != "open":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"la condición ya está {condition.status}")
    await repo.waive(condition, by=user.email, reason=body.reason)
    verdict = await refresh_verdict(session, case_id)
    await session.commit()
    case = await _case_or_404(session, case_id)
    return WaiveResponse(
        condition=condition_result(condition),
        verdict=Verdict(decision=verdict.decision, reasons=[VerdictReason.model_validate(r.model_dump()) for r in verdict.reasons], decided_at=case.verdict_at),
    )

