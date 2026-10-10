"""Case submission shared by the v1 API (``/v1/cases``) and the legacy
``/batches`` API: resolve the process profile, fingerprint the request for
idempotency, store the uploads, and open a case run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fastapi import BackgroundTasks, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from idp.config import Settings
from idp.domain.reprocess import ReprocessScope
from idp.execution.port import executor_for
from idp.persistence.models import Case, CaseRun, Document, ProcessProfileVersion
from idp.persistence.repositories import CaseRepository, CaseRunRepository, DocumentRepository, ProcessProfileRepository, ReviewRepository
from idp.pipeline.orchestrator import case_rules, fail_run
from idp.storage.object_store import ObjectStore, S3ObjectStore


@dataclass(frozen=True)
class Upload:
    filename: str
    content_type: str
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


async def read_uploads(files: list[UploadFile]) -> list[Upload]:
    return [
        Upload(filename=f.filename or "unnamed", content_type=f.content_type or "application/octet-stream", content=await f.read())
        for f in files
    ]


async def resolve_profile_version(session: AsyncSession, key: str, version: int | None) -> ProcessProfileVersion:
    """The requested version if published, else the latest published one.
    422 when the profile or the version cannot be used for new cases."""
    repo = ProcessProfileRepository(session)
    profile = await repo.get_by_key(key)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"perfil de proceso desconocido: '{key}'")
    if version is None:
        row = repo.latest_published(profile)
        if row is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"el perfil '{key}' no tiene ninguna versión publicada")
    else:
        row = await repo.get_version(profile, version)
        if row is None or row.status != "published":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"la versión {version} del perfil '{key}' no está publicada")
    row.profile = profile
    return row


def request_fingerprint(
    *, profile_key: str, profile_version: int | None, external_ref: str | None, channel: str, process_data: dict | None, uploads: list[Upload]
) -> str:
    """Identifies a submission's content, so a retry with the same
    ``Idempotency-Key`` can be told apart from a different request that
    reused the key by mistake."""
    canonical = json.dumps(
        {
            "profile": profile_key,
            "profile_version": profile_version,
            "external_ref": external_ref,
            "channel": channel,
            "process_data": process_data,
            "files": sorted((u.filename, u.sha256) for u in uploads),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def store_uploads(session: AsyncSession, object_store: ObjectStore, case: Case, uploads: list[Upload]) -> list[Document]:
    document_repo = DocumentRepository(session)
    documents: list[Document] = []
    for upload in uploads:
        document = await document_repo.create(case_id=case.id, storage_key="", original_filename=upload.filename)
        document.storage_key = object_store.key_for(tenant=case.tenant, case_id=str(case.id), document_id=str(document.id), filename=upload.filename)
        object_store.put(document.storage_key, upload.content, content_type=upload.content_type)
        documents.append(document)
    return documents


async def open_run(session: AsyncSession, case: Case, *, trigger: str) -> CaseRun:
    return await CaseRunRepository(session).create_next(case, trigger=trigger)


async def open_reprocess_run(session: AsyncSession, settings: Settings, case: Case, scope: ReprocessScope, *, trigger: str) -> CaseRun:
    """A new, immutable run that redoes only what ``scope`` names (VRT-40).
    A document to re-extract is marked ``reextract`` — the run's fan-out
    finds it pending — and keeps its extraction until the new one replaces
    it, so a failed re-extraction loses nothing. Its pending review items
    go; its resolved corrections are re-applied after the new extraction."""
    _unprocessable = status.HTTP_422_UNPROCESSABLE_ENTITY
    documents = {d.id: d for d in case.documents}
    if scope.document_id is not None and scope.document_id not in documents:
        raise HTTPException(status_code=_unprocessable, detail="el documento no pertenece al expediente")
    rules, semantic = await case_rules(settings, session, case)
    if scope.kind == "rule" and scope.rule_id not in {r.rule_id for r in rules}:
        raise HTTPException(status_code=_unprocessable, detail=f"la regla '{scope.rule_id}' no se aplica a este expediente")
    if scope.attribute is not None and (semantic is None or scope.attribute not in {a.key for a in semantic.attributes}):
        raise HTTPException(status_code=_unprocessable, detail=f"el atributo '{scope.attribute}' no está en el catálogo semántico del expediente")

    if scope.reextracts:
        segmented = {d.parent_document_id for d in case.documents if d.parent_document_id is not None}
        targets = [documents[scope.document_id]] if scope.document_id is not None else [d for d in case.documents if d.parent_document_id is None]
        if scope.kind == "document" and (targets[0].parent_document_id is not None or targets[0].id in segmented):
            # Its segments carry their own corrections and audit trail.
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="un documento segmentado no se re-extrae (todavía)")
        review_repo = ReviewRepository(session)
        for document in targets:
            if document.id in segmented:
                continue
            document.status, document.needs_review = "reextract", False
            await review_repo.delete_pending_for_document(document.id)

    run = await open_run(session, case, trigger=trigger)
    run.scope = scope.model_dump(mode="json", exclude_none=True)
    case.status = "uploaded"
    return run


async def dispatch_run(session: AsyncSession, settings: Settings, case: Case, run: CaseRun, background: BackgroundTasks) -> None:
    """Hand the run to the configured executor (VRT-26). If it cannot be
    started (e.g. aeon unreachable), the run is marked failed instead of
    being left pending forever, and the caller gets a 503."""
    try:
        ref = await executor_for(settings).submit(case_id=case.id, run_id=run.id, channel=case.channel, background=background)
    except Exception as exc:
        await fail_run(settings, case.id, run.id, f"no se pudo iniciar la corrida: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="el ejecutor de expedientes no está disponible") from exc
    if ref is not None:
        run.execution_ref = ref
        await session.commit()


class CaseRefused(Exception):
    """A case that cannot be opened or completed, with the reason in words."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def open_case(
    settings: Settings,
    session: AsyncSession,
    *,
    profile: str,
    profile_version: int | None,
    external_ref: str | None,
    channel: str,
    process_data: dict | None,
    uploads: list[Upload],
    idempotency_key: str,
    tenant: str = "default",
) -> tuple[Case, CaseRun]:
    """Open a case with its documents and its first run (not yet handed to
    the executor) — for the channels that are not ``POST /v1/cases``: the
    event bus, MCP, A2A."""
    try:
        version = await resolve_profile_version(session, profile, profile_version)
    except HTTPException as exc:
        raise CaseRefused(str(exc.detail)) from exc
    if not uploads:
        raise CaseRefused("el expediente debe traer al menos un documento")
    case = await CaseRepository(session).create(
        tenant=tenant,
        request_input_payload=process_data,
        profile_version_id=version.id,
        external_ref=external_ref,
        channel=channel,
        idempotency_key=idempotency_key[:256],
        idempotency_fingerprint=request_fingerprint(
            profile_key=profile, profile_version=profile_version, external_ref=external_ref, channel=channel, process_data=process_data, uploads=uploads
        ),
    )
    await store_uploads(session, S3ObjectStore(settings), case, uploads)
    return case, await open_run(session, case, trigger="submit")


async def add_to_case(settings: Settings, session: AsyncSession, case: Case, uploads: list[Upload]) -> CaseRun:
    """Add documents to a case and open the run that re-evaluates it."""
    if not uploads:
        raise CaseRefused("no se recibió ningún documento")
    if await CaseRunRepository(session).has_active_run(case.id):
        raise CaseRefused("el expediente tiene una corrida en curso; reintentar cuando termine")
    await store_uploads(session, S3ObjectStore(settings), case, uploads)
    run = await open_run(session, case, trigger="documents_added")
    case.status = "uploaded"
    return run
