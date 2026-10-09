"""Field accuracy and confidence calibration (VRT-43).
GET  /v1/calibration                     versions, the active one first
POST /v1/calibration                     compute a new version from the labelled observations
GET  /v1/calibration/{version}           its per-field metrics, bins and suggested thresholds
POST /v1/calibration/{version}/activate  review routing uses it from the next run on
POST /v1/calibration/deactivate          back to the raw model confidence
Computing and activating are for admins: activating changes which fields
go to a human."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, require_role
from idp.domain.calibration import MIN_OBSERVATIONS, Calibration, FieldCalibration, calibrate, suggest_threshold
from idp.persistence.models import CalibrationVersion, User
from idp.persistence.repositories import CalibrationRepository, DocumentTypeRepository, SemanticCatalogRepository
from idp.review.labels import describe_field

router = APIRouter(prefix="/v1/calibration", tags=["calibration"], dependencies=[Depends(get_current_user)])
_admin = [Depends(require_role("admin"))]
TARGET_ERRORS = (0.01, 0.02, 0.05)


class VersionSummary(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    report: dict[str, Any]
    created_by: str
    created_at: datetime
    activated_by: str | None
    activated_at: datetime | None


class FieldView(FieldCalibration):
    # What a person reads: the field's business name and its document type's.
    label: str
    document_type_name: str


class VersionDetail(VersionSummary):
    min_observations: int
    fields: list[FieldView]


def _summary(row: CalibrationVersion) -> VersionSummary:
    return VersionSummary(
        id=row.id, version=row.version, status=row.status, report=row.report, created_by=row.created_by,
        created_at=row.created_at, activated_by=row.activated_by, activated_at=row.activated_at,
    )


async def _detail(session: AsyncSession, row: CalibrationVersion) -> VersionDetail:
    model = Calibration.model_validate(row.model)
    types = await DocumentTypeRepository(session).load_catalog()
    loaded = await SemanticCatalogRepository(session).load_active()
    fields = []
    for f in model.fields.values():
        document_type, _, path = f.key.partition(".")
        current = types.current(document_type)
        definition = current[1] if current else None
        label = describe_field(path, document_type=document_type, definition=definition, catalog=loaded[0] if loaded else None, payload=None).label
        name = definition.display_name if definition else document_type
        fields.append(FieldView(**f.model_dump(), label=label, document_type_name=name))
    return VersionDetail(**_summary(row).model_dump(), min_observations=MIN_OBSERVATIONS, fields=fields)


async def _version_or_404(session: AsyncSession, version: int) -> CalibrationVersion:
    row = await CalibrationRepository(session).get(version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="calibration version not found")
    return row


@router.get("", response_model=list[VersionSummary])
async def list_versions(session: AsyncSession = Depends(get_db_session)) -> list[VersionSummary]:
    rows = await CalibrationRepository(session).list_versions()
    return [_summary(r) for r in sorted(rows, key=lambda r: (r.status != "active", -r.version))]


@router.post("", response_model=VersionDetail, status_code=status.HTTP_201_CREATED, dependencies=_admin)
async def compute(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)) -> VersionDetail:
    repo = CalibrationRepository(session)
    observations, counts = await repo.observations()
    if not observations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no hay observaciones etiquetadas: corre una suite de evaluación o resuelve revisiones",
        )
    model = calibrate(observations)
    report = {
        "observations": counts,
        "suggestions": [suggest_threshold(model, observations, target_error=t).model_dump() for t in TARGET_ERRORS],
    }
    row = await repo.create(model=model.model_dump(mode="json"), report=report, created_by=user.name)
    await session.commit()
    return await _detail(session, row)


@router.get("/{version}", response_model=VersionDetail)
async def get_version(version: int, session: AsyncSession = Depends(get_db_session)) -> VersionDetail:
    return await _detail(session, await _version_or_404(session, version))


@router.post("/deactivate", response_model=list[VersionSummary], dependencies=_admin)
async def deactivate(session: AsyncSession = Depends(get_db_session)) -> list[VersionSummary]:
    await CalibrationRepository(session).deactivate()
    await session.commit()
    return await list_versions(session)


@router.post("/{version}/activate", response_model=VersionDetail, dependencies=_admin)
async def activate(version: int, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)) -> VersionDetail:
    row = await _version_or_404(session, version)
    await CalibrationRepository(session).activate(row, by=user.name)
    await session.commit()
    return await _detail(session, row)
