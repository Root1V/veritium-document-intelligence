"""Bulk jobs (VRT-48): many cases at once, from the backoffice.

POST /v1/bulk-jobs                 a ZIP with one folder per case (+ optional manifest) → cases (202; Idempotency-Key)
GET  /v1/bulk-jobs                 list, with how far each one is
GET  /v1/bulk-jobs/template        the manifest to fill, for a profile
GET  /v1/bulk-jobs/{id}            its cases, each with its progress and verdict
GET  /v1/bulk-jobs/{id}/results    one row per case (CSV, opens in Excel)

The cases run in the ``bulk`` lane and are released a few at a time by the
feeder (pipeline/bulk.py); ``bulk_job.completed`` is emitted at the end."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import re
import uuid
import zipfile
from collections import Counter
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from idp.api.case_contract import latest_run
from idp.api.case_service import Upload, resolve_profile_version, store_uploads
from idp.api.deps import get_app_settings, get_current_user, get_db_session, get_object_store, require_role
from idp.config import Settings
from idp.domain.bulk_archive import PROFILE, REFERENCE, Skipped, manifest_path, plan
from idp.domain.case_progress import Progress, progress
from idp.domain.tables import read_table
from idp.persistence.models import BulkJob, Case, CaseRun, ProcessProfileVersion, User
from idp.persistence.repositories import CaseRepository, CaseRunRepository
from idp.pipeline.bulk import outcome
from idp.storage.object_store import S3ObjectStore

router = APIRouter(prefix="/v1/bulk-jobs", tags=["bulk-jobs"], dependencies=[Depends(get_current_user)])

_TENANT = "default"  # multi-tenant arrives with VRT-57
_unprocessable = status.HTTP_422_UNPROCESSABLE_ENTITY
OUTCOME_LABEL = {"continue": "Continuar", "human_review": "Revisión humana", "return_to_client": "Devolver al cliente", "failed": "Con error", "pending": "En curso"}


class BulkJobLinks(BaseModel):
    self: str
    results: str


class BulkJobAccepted(BaseModel):
    id: uuid.UUID
    cases: int
    skipped: list[Skipped]
    replayed: bool
    links: BulkJobLinks


class BulkJobSummary(BaseModel):
    id: uuid.UUID
    name: str
    created_by: str
    created_at: datetime
    finished_at: datetime | None
    cases: int
    # How many cases came to each outcome: continue / human_review / return_to_client / failed / pending.
    outcomes: dict[str, int]
    skipped: list[Skipped]
    links: BulkJobLinks


class BulkJobCase(BaseModel):
    id: uuid.UUID
    external_ref: str | None
    profile: str | None
    outcome: str
    progress: Progress


class BulkJobDetail(BulkJobSummary):
    items: list[BulkJobCase]


def _links(job_id: uuid.UUID) -> BulkJobLinks:
    return BulkJobLinks(self=f"/v1/bulk-jobs/{job_id}", results=f"/v1/bulk-jobs/{job_id}/results")


def _summary(job: BulkJob) -> BulkJobSummary:
    return BulkJobSummary(
        id=job.id, name=job.name, created_by=job.created_by, created_at=job.created_at, finished_at=job.finished_at, cases=len(job.cases),
        outcomes=dict(Counter(outcome(c) for c in job.cases)), skipped=[Skipped.model_validate(s) for s in job.skipped], links=_links(job.id),
    )


def _with_cases(full: bool = False):
    cases = selectinload(BulkJob.cases)
    if not full:
        return (cases,)
    return (
        cases.selectinload(Case.documents),
        cases.selectinload(Case.runs),
        cases.selectinload(Case.profile_version).selectinload(ProcessProfileVersion.profile),
    )


async def _job_or_404(session: AsyncSession, job_id: uuid.UUID) -> BulkJob:
    job = (await session.scalars(select(BulkJob).where(BulkJob.id == job_id).options(*_with_cases(full=True)))).one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bulk job not found")
    return job


def _sha256(file: Any) -> str:
    digest = hashlib.sha256()
    file.seek(0)
    while chunk := file.read(1024 * 1024):
        digest.update(chunk)
    file.seek(0)
    return digest.hexdigest()


@router.post("", response_model=BulkJobAccepted, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_role("integracion", "operador", "admin"))])
async def submit_bulk_job(
    archive: Annotated[UploadFile, File(description="ZIP con una carpeta por expediente; opcional: manifiesto.csv/.xlsx en la raíz.")],
    profile: Annotated[str | None, Form(description="Perfil por defecto para los expedientes que el manifiesto no indique.")] = None,
    name: Annotated[str | None, Form(description="Nombre de la carga; por defecto, el del archivo.")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=256)] = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    object_store: S3ObjectStore = Depends(get_object_store),
    user: User = Depends(get_current_user),
) -> BulkJobAccepted:
    if archive.size is not None and archive.size > settings.bulk_max_archive_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"el archivo pesa más de {settings.bulk_max_archive_mb} MB")
    digest = _sha256(archive.file)
    if idempotency_key is not None:
        existing = (await session.scalars(select(BulkJob).where(BulkJob.tenant == _TENANT, BulkJob.idempotency_key == idempotency_key).options(*_with_cases()))).one_or_none()
        if existing is not None:
            if existing.archive_sha256 != digest:
                raise HTTPException(status_code=_unprocessable, detail="Idempotency-Key ya usada con otro archivo")
            return BulkJobAccepted(id=existing.id, cases=len(existing.cases), skipped=[Skipped.model_validate(s) for s in existing.skipped], replayed=True, links=_links(existing.id))

    try:
        zf = zipfile.ZipFile(archive.file)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=_unprocessable, detail="el archivo no es un ZIP válido") from exc
    with zf:
        files = [(i.filename, i.file_size) for i in zf.infolist() if not i.is_dir()]
        manifest = manifest_path([p for p, _ in files])
        try:
            rows = read_table(manifest, zf.read(manifest)) if manifest else None
            planned, skipped = plan(files, rows, default_profile=profile, max_cases=settings.bulk_max_cases, max_file_bytes=settings.bulk_max_file_mb * 1024 * 1024)
        except ValueError as exc:
            raise HTTPException(status_code=_unprocessable, detail=str(exc)) from exc

        versions: dict[str, ProcessProfileVersion | str] = {}
        for key in {c.profile for c in planned}:
            try:
                versions[key] = await resolve_profile_version(session, key, None)
            except HTTPException as exc:
                versions[key] = str(exc.detail)
        for c in planned:
            if isinstance(versions[c.profile], str):
                skipped.append(Skipped(reference=c.reference, reason=f"{versions[c.profile]}."))
        planned = [c for c in planned if not isinstance(versions[c.profile], str)]
        if not planned:
            reasons = "; ".join(f"{s.reference}: {s.reason}" if s.reference else s.reason for s in skipped[:5])
            raise HTTPException(status_code=_unprocessable, detail=f"el archivo no trae ningún expediente que se pueda procesar. {reasons}".strip())

        job = BulkJob(
            tenant=_TENANT, name=name or archive.filename or "carga masiva", idempotency_key=idempotency_key, archive_sha256=digest,
            skipped=[s.model_dump() for s in skipped], created_by=user.name,
        )
        session.add(job)
        await session.flush()
        cases, runs = CaseRepository(session), CaseRunRepository(session)
        for c in planned:
            version = versions[c.profile]
            assert not isinstance(version, str)
            case = await cases.create(
                tenant=_TENANT, request_input_payload=c.process_data or None, profile_version_id=version.id, external_ref=c.reference, channel="bulk", bulk_job_id=job.id,
            )
            uploads = [
                Upload(filename=path.rsplit("/", 1)[-1], content_type=mimetypes.guess_type(path)[0] or "application/octet-stream", content=zf.read(path))
                for path in c.files
            ]
            await store_uploads(session, object_store, case, uploads)
            run = await runs.create_next(case, trigger="submit")
            run.status = "queued"  # the feeder releases it when there is room in the lane
    await session.commit()
    return BulkJobAccepted(id=job.id, cases=len(planned), skipped=skipped, replayed=False, links=_links(job.id))


@router.get("", response_model=list[BulkJobSummary])
async def list_bulk_jobs(session: AsyncSession = Depends(get_db_session)) -> list[BulkJobSummary]:
    jobs = (await session.scalars(select(BulkJob).order_by(BulkJob.created_at.desc()).limit(50).options(*_with_cases()))).all()
    return [_summary(j) for j in jobs]


@router.get("/template")
async def manifest_template(profile: str, session: AsyncSession = Depends(get_db_session)) -> Response:
    """The manifest for ``profile``: its columns are the process data its conditions read (``request.<campo>``)."""
    version = await resolve_profile_version(session, profile, None)
    fields = sorted(set(re.findall(r"\brequest\.([A-Za-z_]\w*)", json.dumps(version.definition))))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([REFERENCE, PROFILE, *fields])
    writer.writerow(["EXP-0001", profile, *("" for _ in fields)])
    return Response(
        "﻿" + out.getvalue(),  # the BOM makes Excel read the accents as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="manifiesto-{profile}.csv"'},
    )


@router.get("/{job_id}", response_model=BulkJobDetail)
async def get_bulk_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> BulkJobDetail:
    job = await _job_or_404(session, job_id)
    items = []
    for c in job.cases:
        run: CaseRun | None = latest_run(c)
        items.append(
            BulkJobCase(
                id=c.id, external_ref=c.external_ref, profile=c.profile_version.profile.key if c.profile_version else None, outcome=outcome(c),
                progress=progress(c.status, run.status if run else None, [d.status for d in c.documents]),
            )
        )
    return BulkJobDetail(**_summary(job).model_dump(), items=items)


@router.get("/{job_id}/results")
async def bulk_job_results(job_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> Response:
    job = await _job_or_404(session, job_id)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["expediente", "perfil", "resultado", "motivos", "id"])
    for c in job.cases:
        reasons = list(dict.fromkeys(r.get("message", "") for r in (c.verdict_reasons or []) if outcome(c) not in ("pending", "failed")))
        writer.writerow([c.external_ref, c.profile_version.profile.key if c.profile_version else "", OUTCOME_LABEL[outcome(c)], " | ".join(reasons), str(c.id)])
    processed = {c.external_ref for c in job.cases}
    for s in job.skipped:
        # A file left out of a case that went ahead, or a whole case that did not.
        label = "Archivo omitido" if s.get("reference") in processed else "Expediente no procesado"
        writer.writerow([s.get("reference") or "", "", label, s.get("reason", ""), ""])
    return Response(
        "﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="resultados-{job.id.hex[:8]}.csv"'},
    )
