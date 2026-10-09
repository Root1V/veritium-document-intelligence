"""Commands received as CloudEvents (VRT-49), whatever the transport — the
bus consumer or ``POST /v1/events``:

- ``pe.veritium.case.submit``: create a case (what ``POST /v1/cases`` does);
- ``pe.veritium.case.documents.add``: add documents to a case, by its id or
  its ``external_ref``.

Documents come by claim-check (``documents[].url``). Every command is
answered with ``pe.veritium.command.accepted`` or ``.rejected`` through the
outbox (so on the bus and by webhook), quoting the command's id and source.
A command already answered — same source and id, CloudEvents' identity —
gets the same answer again and does nothing."""

from __future__ import annotations

import json
import mimetypes
import uuid
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.case_service import Upload, open_run, request_fingerprint, resolve_profile_version, store_uploads
from idp.config import Settings
from idp.events.claim_check import ClaimCheckError, fetch
from idp.execution.handover import hand_over
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, CaseRun, OutboxEvent
from idp.persistence.repositories import CaseRepository, CaseRunRepository
from idp.storage.object_store import S3ObjectStore
from idp.webhooks.events import COMMAND_ACCEPTED, COMMAND_REJECTED, emit_command_answer

SUBMIT = "pe.veritium.case.submit"
ADD_DOCUMENTS = "pe.veritium.case.documents.add"
COMMAND_TYPES = (SUBMIT, ADD_DOCUMENTS)
_TENANT = "default"  # multi-tenant arrives with VRT-57


class DocumentRef(BaseModel):
    url: str
    filename: str | None = None


class SubmitData(BaseModel):
    profile: str
    profile_version: int | None = None
    external_ref: str | None = None
    channel: Literal["online", "backoffice", "bulk"] = "backoffice"
    process_data: dict[str, Any] | None = None
    documents: list[DocumentRef] = Field(min_length=1)


class AddDocumentsData(BaseModel):
    case_id: uuid.UUID | None = None
    external_ref: str | None = None
    documents: list[DocumentRef] = Field(min_length=1)

    @model_validator(mode="after")
    def _names_a_case(self) -> AddDocumentsData:
        if self.case_id is None and not self.external_ref:
            raise ValueError("indica case_id o external_ref")
        return self


class Answer(BaseModel):
    accepted: bool
    case_id: uuid.UUID | None = None
    run_number: int | None = None
    reason: str | None = None
    replayed: bool = False


class Rejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- CloudEvents bindings ----------------------------------------------------


def _checked(event: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in ("specversion", "id", "source", "type") if not event.get(k)]
    if missing:
        raise ValueError(f"no es un CloudEvent válido: falta {', '.join(missing)}")
    if event["specversion"] != "1.0":
        raise ValueError("solo se admite CloudEvents 1.0")
    return event


def structured(body: bytes) -> dict[str, Any]:
    """Structured mode: the whole event as JSON (HTTP and Kafka bindings)."""
    try:
        event = json.loads(body)
    except ValueError as exc:
        raise ValueError(f"el evento no es JSON válido: {exc}") from exc
    if not isinstance(event, dict):
        raise ValueError("el evento debe ser un objeto JSON")
    return _checked(event)


def binary(attributes: dict[str, str], body: bytes) -> dict[str, Any]:
    """Binary mode: attributes in headers (``ce-``/``ce_`` already stripped), data in the body."""
    event: dict[str, Any] = dict(attributes)
    try:
        event["data"] = json.loads(body) if body else None
    except ValueError as exc:
        raise ValueError(f"los datos del evento no son JSON válido: {exc}") from exc
    return _checked(event)


# --- Handling -----------------------------------------------------------------


async def _previous_answer(session: AsyncSession, event: dict[str, Any]) -> Answer | None:
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.type.in_((COMMAND_ACCEPTED, COMMAND_REJECTED)),
            OutboxEvent.data["command_id"].astext == str(event["id"]),
            OutboxEvent.data["command_source"].astext == str(event["source"]),
        )
        .limit(1)
    )
    previous = await session.scalar(stmt)
    if previous is None:
        return None
    data = previous.data
    if previous.type == COMMAND_REJECTED:
        return Answer(accepted=False, reason=data.get("reason"), replayed=True)
    return Answer(accepted=True, case_id=uuid.UUID(data["case_id"]), run_number=data.get("run_number"), replayed=True)


async def _uploads(settings: Settings, documents: list[DocumentRef]) -> list[Upload]:
    uploads = []
    for d in documents:
        try:
            content = await fetch(settings, d.url)
        except ClaimCheckError as exc:
            raise Rejected(str(exc)) from exc
        filename = d.filename or d.url.rstrip("/").rsplit("/", 1)[-1] or "documento"
        uploads.append(Upload(filename=filename, content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream", content=content))
    return uploads


async def _submit(settings: Settings, session: AsyncSession, event: dict[str, Any], data: SubmitData) -> tuple[Case, CaseRun]:
    try:
        version = await resolve_profile_version(session, data.profile, data.profile_version)
    except HTTPException as exc:
        raise Rejected(str(exc.detail)) from exc
    uploads = await _uploads(settings, data.documents)
    case = await CaseRepository(session).create(
        tenant=_TENANT,
        request_input_payload=data.process_data,
        profile_version_id=version.id,
        external_ref=data.external_ref,
        channel=data.channel,
        idempotency_key=f"ce:{event['source']}:{event['id']}"[:256],
        idempotency_fingerprint=request_fingerprint(
            profile_key=data.profile, profile_version=data.profile_version, external_ref=data.external_ref, channel=data.channel,
            process_data=data.process_data, uploads=uploads,
        ),
    )
    await store_uploads(session, S3ObjectStore(settings), case, uploads)
    return case, await open_run(session, case, trigger="submit")


async def _add_documents(settings: Settings, session: AsyncSession, data: AddDocumentsData) -> tuple[Case, CaseRun]:
    stmt = select(Case).where(Case.id == data.case_id) if data.case_id else select(Case).where(Case.external_ref == data.external_ref).order_by(Case.created_at.desc()).limit(1)
    case = await session.scalar(stmt)
    if case is None:
        raise Rejected("no existe el expediente indicado")
    if await CaseRunRepository(session).has_active_run(case.id):
        raise Rejected("el expediente tiene una corrida en curso; reintentar cuando termine")
    uploads = await _uploads(settings, data.documents)
    await store_uploads(session, S3ObjectStore(settings), case, uploads)
    run = await open_run(session, case, trigger="documents_added")
    case.status = "uploaded"
    return case, run


async def handle(settings: Settings, event: dict[str, Any]) -> Answer:
    """Carry out one command and answer it (see the module docstring)."""
    async with get_session_factory(settings)() as session:
        if (previous := await _previous_answer(session, event)) is not None:
            return previous
        try:
            if event["type"] not in COMMAND_TYPES:
                raise Rejected(f"tipo de comando desconocido: {event['type']}; se aceptan {', '.join(COMMAND_TYPES)}")
            try:
                payload = SubmitData.model_validate(event.get("data")) if event["type"] == SUBMIT else AddDocumentsData.model_validate(event.get("data"))
            except ValidationError as exc:
                raise Rejected("datos del comando inválidos: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from exc
            case, run = await (_submit(settings, session, event, payload) if isinstance(payload, SubmitData) else _add_documents(settings, session, payload))
        except Rejected as rejected:
            await session.rollback()
            emit_command_answer(session, tenant=_TENANT, command=event, reason=rejected.reason)
            await session.commit()
            return Answer(accepted=False, reason=rejected.reason)
        emit_command_answer(session, tenant=_TENANT, command=event, case=case, run_number=run.run_number)
        await session.commit()
        answer = Answer(accepted=True, case_id=case.id, run_number=run.run_number)
        pending, channel = [(case.id, run.id)], case.channel
    await hand_over(settings, pending, channel=channel)
    return answer
