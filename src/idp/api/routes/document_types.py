"""Document type catalog (VRT-32, ADR-0008).

GET  /document-types                                     the published types as the web shows them ("Plantillas"),
                                                         plus accepted-but-unregistered type suggestions
GET  /v1/document-types                                  every type and its versions (summary)
GET  /v1/document-types/{key}/versions/{version}         one version, with its definition
POST /v1/document-types                                  new type, as draft v1 (admin)
POST /v1/document-types/{key}/versions                   new draft version (admin)
POST /v1/document-types/{key}/versions/{version}/publish draft -> published (admin)
POST /v1/document-types/{key}/versions/{version}/retire  published -> retired (admin)

A definition is validated by its Pydantic model (422). Publishing also
checks it against what already points at the type: every semantic mapping
of the published catalog for this type must still name a field of the new
schema (409), so a schema change cannot silently drop what the semantic
layer reads. A published version is immutable; its extractions record it."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_current_user, get_db_session, require_role
from idp.domain.document_type_catalog import DocumentTypeDefinition, FieldSpec, compile_schema
from idp.domain.semantic import SemanticCatalog
from idp.persistence.models import DocumentTypeRecord, DocumentTypeVersion, User
from idp.persistence.repositories import DocumentTypeRepository, SemanticCatalogRepository, TypeSuggestionRepository

router = APIRouter(prefix="/document-types", tags=["document-types"], dependencies=[Depends(get_current_user)])
admin_router = APIRouter(prefix="/v1/document-types", tags=["document-types"], dependencies=[Depends(get_current_user)])


# --- GET /document-types (web) ----------------------------------------------


class FieldInfo(BaseModel):
    name: str
    field_type: str
    description: str | None
    required: bool
    items: list[FieldInfo] | None = None


class DocumentTypeInfo(BaseModel):
    name: str
    display_name: str
    version: int
    description: str
    fields: list[FieldInfo]


class PendingTypeInfo(BaseModel):
    suggestion_id: str
    suggested_type_name: str
    suggested_display_name: str
    rationale: str
    fields: list[dict]


class DocumentTypeCatalogResponse(BaseModel):
    registered: list[DocumentTypeInfo]
    pending: list[PendingTypeInfo]


def _field_info(spec: FieldSpec) -> FieldInfo:
    if spec.type == "list":
        kind = f"list[{spec.item_name}]"
    elif spec.type == "enum":
        kind = " | ".join(spec.enum_values or [])
    else:
        kind = spec.type
    return FieldInfo(
        name=spec.name,
        field_type=kind,
        description=spec.description,
        required=spec.required,
        items=[_field_info(i) for i in spec.items] if spec.items else None,
    )


@router.get("", response_model=DocumentTypeCatalogResponse)
async def get_document_type_catalog(session: AsyncSession = Depends(get_db_session)) -> DocumentTypeCatalogResponse:
    catalog = await DocumentTypeRepository(session).load_catalog()
    registered = []
    for key in catalog.keys():
        version, definition = catalog.current(key)  # type: ignore[misc]
        registered.append(
            DocumentTypeInfo(
                name=key,
                display_name=definition.display_name,
                version=version,
                description=definition.description,
                fields=[_field_info(f) for f in definition.fields],
            )
        )
    accepted_suggestions = await TypeSuggestionRepository(session).list_by_status("accepted")
    pending = [
        PendingTypeInfo(
            suggestion_id=str(row.id),
            suggested_type_name=row.suggested_type_name,
            suggested_display_name=row.suggested_display_name,
            rationale=row.rationale,
            fields=row.fields,
        )
        for row in accepted_suggestions
    ]
    return DocumentTypeCatalogResponse(registered=registered, pending=pending)


# --- /v1/document-types (administration) -----------------------------------


class TypeVersionSummary(BaseModel):
    version: int
    status: str
    content_hash: str
    created_by: str | None
    created_at: datetime
    published_by: str | None
    published_at: datetime | None
    retired_at: datetime | None


class TypeVersionDetail(TypeVersionSummary):
    key: str
    definition: DocumentTypeDefinition


class DocumentTypeResponse(BaseModel):
    id: uuid.UUID
    key: str
    active_version: int | None
    versions: list[TypeVersionSummary]


def _summary(v: DocumentTypeVersion) -> TypeVersionSummary:
    return TypeVersionSummary(
        version=v.version, status=v.status, content_hash=v.content_hash, created_by=v.created_by, created_at=v.created_at,
        published_by=v.published_by, published_at=v.published_at, retired_at=v.retired_at,
    )


def _detail(record: DocumentTypeRecord, v: DocumentTypeVersion) -> TypeVersionDetail:
    return TypeVersionDetail(**_summary(v).model_dump(), key=record.key, definition=DocumentTypeDefinition.model_validate(v.definition))


def _response(record: DocumentTypeRecord) -> DocumentTypeResponse:
    published = [v.version for v in record.versions if v.status == "published"]
    return DocumentTypeResponse(id=record.id, key=record.key, active_version=max(published) if published else None, versions=[_summary(v) for v in record.versions])


async def _type_or_404(repo: DocumentTypeRepository, key: str) -> DocumentTypeRecord:
    record = await repo.get_by_key(key)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tipo documental '{key}' no encontrado")
    return record


def _version_or_404(record: DocumentTypeRecord, version: int) -> DocumentTypeVersion:
    row = next((v for v in record.versions if v.version == version), None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"versión {version} de '{record.key}' no encontrada")
    return row


def _compiles(definition: DocumentTypeDefinition) -> None:
    try:
        compile_schema(definition)
    except Exception as exc:  # a definition can pass its own validation and still not compile (e.g. a name clash)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"el esquema no compila: {exc}") from exc


_INDEX = re.compile(r"\[\d+\]")


def unmapped_paths(definition: DocumentTypeDefinition, catalog: SemanticCatalog) -> list[str]:
    """Semantic mappings for this type that the schema no longer has."""
    paths = definition.field_paths()
    return sorted({p for m in catalog.mappings_for(definition.key) for p in m.field_paths if _INDEX.sub("[]", p) not in paths})


@admin_router.get("", response_model=list[DocumentTypeResponse])
async def list_document_types(session: AsyncSession = Depends(get_db_session)) -> list[DocumentTypeResponse]:
    return [_response(r) for r in await DocumentTypeRepository(session).list_types()]


@admin_router.get("/{key}/versions/{version}", response_model=TypeVersionDetail)
async def get_document_type_version(key: str, version: int, session: AsyncSession = Depends(get_db_session)) -> TypeVersionDetail:
    record = await _type_or_404(DocumentTypeRepository(session), key)
    return _detail(record, _version_or_404(record, version))


@admin_router.post("", response_model=TypeVersionDetail, status_code=status.HTTP_201_CREATED)
async def create_document_type(
    definition: DocumentTypeDefinition, session: AsyncSession = Depends(get_db_session), user: User = Depends(require_role("admin"))
) -> TypeVersionDetail:
    repo = DocumentTypeRepository(session)
    if await repo.get_by_key(definition.key) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"el tipo '{definition.key}' ya existe; crea una versión nueva")
    _compiles(definition)
    row = await repo.create_type(definition, created_by=user.email)
    return _detail(await _type_or_404(repo, definition.key), row)


@admin_router.post("/{key}/versions", response_model=TypeVersionDetail, status_code=status.HTTP_201_CREATED)
async def create_document_type_draft(
    key: str, definition: DocumentTypeDefinition, session: AsyncSession = Depends(get_db_session), user: User = Depends(require_role("admin"))
) -> TypeVersionDetail:
    if definition.key != key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"la definición es de '{definition.key}', no de '{key}'")
    repo = DocumentTypeRepository(session)
    record = await _type_or_404(repo, key)
    _compiles(definition)
    row = await repo.create_draft(record, definition, created_by=user.email)
    return _detail(await _type_or_404(repo, key), row)


@admin_router.post("/{key}/versions/{version}/publish", response_model=TypeVersionDetail)
async def publish_document_type_version(
    key: str, version: int, session: AsyncSession = Depends(get_db_session), user: User = Depends(require_role("admin"))
) -> TypeVersionDetail:
    repo = DocumentTypeRepository(session)
    record = await _type_or_404(repo, key)
    row = _version_or_404(record, version)
    if row.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"solo se publica un borrador (está '{row.status}')")
    active = await SemanticCatalogRepository(session).load_active()
    if active is not None:
        missing = unmapped_paths(DocumentTypeDefinition.model_validate(row.definition), active[0])
        if missing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"el catálogo semántico v{active[1]} lee de '{key}' campos que esta versión no tiene: {missing}",
            )
    return _detail(record, await repo.set_status(row, status="published", actor=user.email))


@admin_router.post("/{key}/versions/{version}/retire", response_model=TypeVersionDetail)
async def retire_document_type_version(
    key: str, version: int, session: AsyncSession = Depends(get_db_session), user: User = Depends(require_role("admin"))
) -> TypeVersionDetail:
    repo = DocumentTypeRepository(session)
    record = await _type_or_404(repo, key)
    row = _version_or_404(record, version)
    if row.status != "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"solo se retira una versión publicada (está '{row.status}')")
    return _detail(record, await repo.set_status(row, status="retired", actor=user.email))
