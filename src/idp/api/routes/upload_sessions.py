"""Upload sessions with a quick check (VRT-47) — how an online front-end
hands the upload to the person whose documents they are.
POST   /v1/upload-sessions                    open one (the calling system); returns its link and token, once
GET    /v1/upload-sessions/{id}               what is asked and what was uploaded            (X-Upload-Token)
POST   /v1/upload-sessions/{id}/files         upload a file: checked and answered in seconds (X-Upload-Token)
DELETE /v1/upload-sessions/{id}/files/{fid}   take a file back                               (X-Upload-Token)
POST   /v1/upload-sessions/{id}/submit        send: the case is created (or completed) and processed (X-Upload-Token)
The token lives only in the link: whoever has it can upload until the
session is sent or expires, and nothing else."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from idp.api.case_service import dispatch_run, open_run, resolve_profile_version
from idp.api.deps import get_app_settings, get_current_user, get_db_session, get_object_store, require_role
from idp.config import Settings
from idp.domain.process_profile import ProcessProfileDefinition
from idp.domain.quick_check import Check, verdict
from idp.persistence.models import ProcessProfileVersion, UploadedFile, UploadSession, User
from idp.persistence.repositories import CaseRepository, CaseRunRepository, DocumentRepository, DocumentTypeRepository
from idp.pipeline.orchestrator import load_semantic_catalog
from idp.pipeline.quick_check import check_file
from idp.validation.cel import CelEvaluationError, compile_expression, evaluate
from idp.storage.object_store import S3ObjectStore

router = APIRouter(prefix="/v1/upload-sessions", tags=["upload-sessions"])
_TENANT = "default"


class SessionRequest(BaseModel):
    profile: str = Field(description="Clave del perfil de proceso, p. ej. 'convenios'.")
    profile_version: int | None = None
    external_ref: str | None = None
    process_data: dict[str, Any] | None = None
    case_id: uuid.UUID | None = Field(default=None, description="Completar un expediente existente en vez de crear uno.")
    minutes: int | None = Field(default=None, ge=5, le=24 * 60, description="Vigencia del enlace; por defecto la configurada.")


class SessionCreated(BaseModel):
    id: uuid.UUID
    token: str = Field(description="Solo se entrega aquí; va en el enlace.")
    upload_url: str
    expires_at: datetime


class Requirement(BaseModel):
    key: str
    label: str
    document_types: list[str]
    required: bool
    covered: bool


class FileView(BaseModel):
    id: uuid.UUID
    filename: str
    size: int
    requirement_key: str | None
    detected_type: str | None
    detected_type_name: str | None
    page_count: int
    checks: list[Check]
    verdict: str
    check_ms: int | None
    created_at: datetime


class SessionView(BaseModel):
    id: uuid.UUID
    process_name: str
    external_ref: str | None
    status: str
    expires_at: datetime
    requirements: list[Requirement]
    files: list[FileView]
    submitted_case_id: uuid.UUID | None
    max_file_mb: int


class Submitted(BaseModel):
    case_id: uuid.UUID
    reference: str
    files: int


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _load(session: AsyncSession, session_id: uuid.UUID) -> UploadSession | None:
    stmt = (
        select(UploadSession)
        .where(UploadSession.id == session_id)
        .options(selectinload(UploadSession.files), selectinload(UploadSession.profile_version).selectinload(ProcessProfileVersion.profile))
        .execution_options(populate_existing=True)
    )
    return await session.scalar(stmt)


async def _by_token(
    session_id: uuid.UUID, token: Annotated[str, Header(alias="X-Upload-Token")], session: AsyncSession = Depends(get_db_session)
) -> UploadSession:
    upload = await _load(session, session_id)
    if upload is None or not secrets.compare_digest(upload.token_hash, _hash(token)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="el enlace no es válido")
    if upload.status == "open" and upload.expires_at < datetime.now(UTC):
        upload.status = "expired"
        await session.commit()
    if upload.status == "expired":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="el enlace venció; pide uno nuevo")
    return upload


async def _requirements(session: AsyncSession, upload: UploadSession, files: list[UploadedFile]) -> list[Requirement]:
    """What the profile asks for, as the person sees it: a requirement the
    process data rules out is not shown; one whose condition needs the
    documents themselves shows as "if it applies"."""
    definition = ProcessProfileDefinition.model_validate(upload.profile_version.definition)
    loaded = await load_semantic_catalog(session, upload.profile_version.semantic_catalog_version)
    mappings = loaded[0].mappings if loaded else []
    usable = [f for f in files if not f.removed and f.verdict != "reject"]
    out = []
    for item in definition.checklist:
        required = item.required
        if item.required_when_cel:
            try:
                if not evaluate(compile_expression(item.required_when_cel), {"request": upload.request_input_payload or {}, "case": {}}):
                    continue  # ruled out by the process data
            except CelEvaluationError:
                required = False  # depends on what the documents say
        if item.document_type:
            types = [item.document_type]
        else:  # by attribute: any type the semantic catalog maps it from
            mapped = {m.document_type for m in mappings if m.attribute in item.requires_attributes and m.role == item.role}
            types = sorted(mapped & set(item.accepted_document_types) if item.accepted_document_types is not None else mapped)
        covered = any(f.requirement_key == item.key or (f.detected_type is not None and f.detected_type in types) for f in usable)
        out.append(Requirement(key=item.key, label=item.label, document_types=types, required=required, covered=covered))
    return out


async def _view(session: AsyncSession, upload: UploadSession, settings: Settings) -> SessionView:
    catalog = await DocumentTypeRepository(session).load_catalog()
    names = {k: c[1].display_name for k in catalog.keys() if (c := catalog.current(k))}
    files = [f for f in upload.files if not f.removed]
    return SessionView(
        id=upload.id, process_name=upload.profile_version.profile.name, external_ref=upload.external_ref, status=upload.status,
        expires_at=upload.expires_at, requirements=await _requirements(session, upload, files), submitted_case_id=upload.submitted_case_id,
        max_file_mb=settings.upload_max_file_mb,
        files=[
            FileView(
                id=f.id, filename=f.filename, size=f.size, requirement_key=f.requirement_key, detected_type=f.detected_type,
                detected_type_name=names.get(f.detected_type or ""), page_count=f.page_count,
                checks=[Check.model_validate(c) for c in f.checks], verdict=f.verdict, check_ms=f.check_ms, created_at=f.created_at,
            )
            for f in files
        ],
    )


async def create_session(session: AsyncSession, settings: Settings, body: SessionRequest, *, created_by: str) -> SessionCreated:
    """Open an upload session — for this route and for MCP (VRT-53)."""
    if body.case_id is not None:
        case = await CaseRepository(session).get(body.case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
        version_id = case.profile_version_id
        if version_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="el expediente no tiene perfil de proceso")
    else:
        version_id = (await resolve_profile_version(session, body.profile, body.profile_version)).id
    token = secrets.token_urlsafe(32)
    upload = UploadSession(
        token_hash=_hash(token), profile_version_id=version_id, case_id=body.case_id, external_ref=body.external_ref,
        request_input_payload=body.process_data, created_by=created_by,
        expires_at=datetime.now(UTC) + timedelta(minutes=body.minutes or settings.upload_session_minutes),
    )
    session.add(upload)
    await session.commit()
    # The token goes after '#': browsers never send it to a server in the URL.
    return SessionCreated(id=upload.id, token=token, upload_url=f"{settings.public_upload_base_url}/carga/{upload.id}#t={token}", expires_at=upload.expires_at)


@router.post(
    "", response_model=SessionCreated, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("integracion", "operador", "admin"))],
)
async def open_session(
    body: SessionRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(get_current_user),
) -> SessionCreated:
    return await create_session(session, settings, body, created_by=user.name)


@router.get("/{session_id}", response_model=SessionView)
async def get_session(
    upload: UploadSession = Depends(_by_token), session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_app_settings)
) -> SessionView:
    return await _view(session, upload, settings)


@router.post("/{session_id}/files", response_model=FileView, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: Annotated[UploadFile, File()],
    requirement_key: Annotated[str | None, Form()] = None,
    upload: UploadSession = Depends(_by_token),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    object_store: S3ObjectStore = Depends(get_object_store),
) -> FileView:
    if upload.status != "open":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="los documentos ya se enviaron")
    if sum(not f.removed for f in upload.files) >= settings.upload_max_files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"se aceptan hasta {settings.upload_max_files} archivos")
    data = await file.read()
    if len(data) > settings.upload_max_file_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"el archivo supera {settings.upload_max_file_mb} MB")
    requirement = next((r for r in await _requirements(session, upload, list(upload.files)) if r.key == requirement_key), None) if requirement_key else None

    started = time.monotonic()
    expected = requirement.document_types[0] if requirement and len(requirement.document_types) == 1 else None
    checked = await check_file(settings, session, data, expected_type=expected)
    facts, detected, checks = checked.facts, checked.detected_type, checked.checks

    file_id = uuid.uuid4()
    filename = file.filename or "documento"
    key = f"{_TENANT}/upload-sessions/{upload.id}/{file_id}/{filename}"
    await asyncio.to_thread(object_store.put, key, data, file.content_type or "application/octet-stream")
    row = UploadedFile(
        id=file_id, session_id=upload.id, filename=filename, content_type=file.content_type or "application/octet-stream", size=len(data),
        storage_key=key, requirement_key=requirement.key if requirement else None, detected_type=detected if detected != "otro" else None,
        page_count=facts.page_count, checks=[c.model_dump() for c in checks], verdict=verdict(checks), check_ms=int((time.monotonic() - started) * 1000),
    )
    session.add(row)
    await session.commit()
    refreshed = await _load(session, upload.id)
    assert refreshed is not None
    view = await _view(session, refreshed, settings)
    return next(f for f in view.files if f.id == file_id)


@router.delete("/{session_id}/files/{file_id}", response_model=SessionView)
async def remove_file(
    file_id: uuid.UUID,
    upload: UploadSession = Depends(_by_token),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> SessionView:
    if upload.status != "open":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="los documentos ya se enviaron")
    row = next((f for f in upload.files if f.id == file_id), None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    row.removed = True
    await session.commit()
    return await _view(session, upload, settings)


@router.post("/{session_id}/submit", response_model=Submitted)
async def submit(
    background: BackgroundTasks,
    upload: UploadSession = Depends(_by_token),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> Submitted:
    """Sends the files that can be read; a rejected one stays out. Sending
    twice returns the same case."""
    files = [f for f in upload.files if not f.removed and f.verdict != "reject"]
    if upload.status == "submitted" and upload.submitted_case_id is not None:
        case = await CaseRepository(session).get(upload.submitted_case_id)
        return Submitted(case_id=upload.submitted_case_id, reference=(case.external_ref if case else None) or str(upload.submitted_case_id)[:8], files=len(files))
    if not files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="no hay documentos que se puedan leer para enviar")

    repo = CaseRepository(session)
    if upload.case_id is not None:
        case = await repo.get(upload.case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
        if await CaseRunRepository(session).has_active_run(case.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="el expediente se está procesando; intenta en unos minutos")
        trigger = "documents_added"
    else:
        case = await repo.create(
            tenant=_TENANT, request_input_payload=upload.request_input_payload, profile_version_id=upload.profile_version_id,
            external_ref=upload.external_ref, channel=upload.channel,
        )
        trigger = "submit"
    documents = DocumentRepository(session)
    for f in files:
        await documents.create(case_id=case.id, storage_key=f.storage_key, original_filename=f.filename)
    run = await open_run(session, case, trigger=trigger)
    case.status = "uploaded"
    upload.status, upload.submitted_at, upload.submitted_case_id = "submitted", datetime.now(UTC), case.id
    await session.commit()
    await dispatch_run(session, settings, case, run, background)
    return Submitted(case_id=case.id, reference=case.external_ref or str(case.id)[:8], files=len(files))
