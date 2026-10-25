"""Semantic catalog administration (VRT-23, ADR-0007).

GET  /v1/semantic-catalog                       the latest published version
GET  /v1/semantic-catalog/versions              all versions (summary)
GET  /v1/semantic-catalog/versions/{version}    one version, with its catalog
POST /v1/semantic-catalog/versions              new draft (admin); the catalog is validated on the way in (422 if inconsistent),
                                                and its mappings against the published document types (400)
PUT  /v1/semantic-catalog/versions/{version}            a draft, edited in place (admin; VRT-89)
POST /v1/semantic-catalog/versions/{version}/publish   draft -> published (admin)
DELETE /v1/semantic-catalog/versions/{version}          a draft, for good (admin; VRT-72)

Published versions are immutable: a change is always a new draft version.
The web page is /semantic-catalog (VRT-34)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, require_platform
from idp.domain.document_type_catalog import DocumentTypeCatalog
from idp.domain.semantic import SemanticCatalog
from idp.persistence.models import SemanticCatalogVersion, User
from idp.persistence.repositories import DocumentTypeRepository, SemanticCatalogRepository

router = APIRouter(prefix="/v1/semantic-catalog", tags=["semantic-catalog"], dependencies=[Depends(get_current_user)])


class CatalogVersionSummary(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    content_hash: str
    created_by: str | None
    created_at: datetime
    published_by: str | None
    published_at: datetime | None


class CatalogVersionDetail(CatalogVersionSummary):
    catalog: SemanticCatalog


_INDEX = re.compile(r"\[\d+\]")


def mapping_errors(catalog: SemanticCatalog, types: DocumentTypeCatalog) -> list[str]:
    """A mapping must read a field that exists: a published document type
    and a path of its current schema (VRT-34; the type side checks the same
    when a new schema is published, VRT-32)."""
    errors = []
    for m in catalog.mappings:
        current = types.current(m.document_type)
        if current is None:
            errors.append(f"mapeo {m.document_type}: no hay un tipo documental publicado con esa clave")
            continue
        paths = current[1].field_paths()
        errors += [f"mapeo {m.document_type}.{p}: el esquema v{current[0]} no tiene ese campo" for p in m.field_paths if _INDEX.sub("[]", p) not in paths]
    return errors


def _summary(row: SemanticCatalogVersion) -> CatalogVersionSummary:
    return CatalogVersionSummary(
        id=row.id,
        version=row.version,
        status=row.status,
        content_hash=row.content_hash,
        created_by=row.created_by,
        created_at=row.created_at,
        published_by=row.published_by,
        published_at=row.published_at,
    )


def _detail(row: SemanticCatalogVersion) -> CatalogVersionDetail:
    return CatalogVersionDetail(**_summary(row).model_dump(), catalog=SemanticCatalog.model_validate(row.definition))


@router.get("", response_model=CatalogVersionDetail)
async def get_active_catalog(session: AsyncSession = Depends(get_db_session)) -> CatalogVersionDetail:
    row = await SemanticCatalogRepository(session).latest_published()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no published semantic catalog")
    return _detail(row)


@router.get("/versions", response_model=list[CatalogVersionSummary])
async def list_catalog_versions(session: AsyncSession = Depends(get_db_session)) -> list[CatalogVersionSummary]:
    return [_summary(row) for row in await SemanticCatalogRepository(session).list_versions()]


@router.get("/versions/{version}", response_model=CatalogVersionDetail)
async def get_catalog_version(version: int, session: AsyncSession = Depends(get_db_session)) -> CatalogVersionDetail:
    row = await SemanticCatalogRepository(session).get_version(version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="catalog version not found")
    return _detail(row)


@router.post("/versions", response_model=CatalogVersionDetail, status_code=status.HTTP_201_CREATED)
async def create_catalog_draft(
    catalog: SemanticCatalog,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_platform("admin")),
) -> CatalogVersionDetail:
    errors = mapping_errors(catalog, await DocumentTypeRepository(session).load_catalog())
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors)
    row = await SemanticCatalogRepository(session).create_draft(catalog, created_by=user.email)
    return _detail(row)


@router.put("/versions/{version}", response_model=CatalogVersionDetail)
async def update_catalog_draft(
    version: int,
    catalog: SemanticCatalog,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_platform("admin")),
) -> CatalogVersionDetail:
    repo = SemanticCatalogRepository(session)
    row = await repo.get_version(version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="catalog version not found")
    if row.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"version {version} is already {row.status}; published versions are immutable")
    errors = mapping_errors(catalog, await DocumentTypeRepository(session).load_catalog())
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors)
    return _detail(await repo.update_draft(row, catalog))


@router.post("/versions/{version}/publish", response_model=CatalogVersionDetail)
async def publish_catalog_version(
    version: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_platform("admin")),
) -> CatalogVersionDetail:
    repo = SemanticCatalogRepository(session)
    row = await repo.get_version(version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="catalog version not found")
    if row.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"version {version} is already {row.status}; published versions are immutable")
    return _detail(await repo.publish(row, published_by=user.email))


@router.delete("/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog_draft(version: int, session: AsyncSession = Depends(get_db_session), _: User = Depends(require_platform("admin"))) -> Response:
    row = await SemanticCatalogRepository(session).get_version(version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="catalog version not found")
    if row.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="solo se elimina un borrador: los procesos fijan las versiones publicadas")
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
