"""Case submission shared by the v1 API (``/v1/cases``) and the legacy
``/batches`` API: resolve the process profile, fingerprint the request for
idempotency, store the uploads, and open a case run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from idp.persistence.models import Case, CaseRun, Document, ProcessProfileVersion
from idp.persistence.repositories import CaseRunRepository, DocumentRepository, ProcessProfileRepository
from idp.storage.object_store import ObjectStore


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
