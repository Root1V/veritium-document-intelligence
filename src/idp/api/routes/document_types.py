"""Document type catalog (VRT-32, ADR-0008).

GET  /document-types                                     the published types as the web shows them ("Plantillas"),
                                                         plus accepted-but-unregistered type suggestions
GET  /v1/document-types                                  every type and its versions (summary)
GET  /v1/document-types/{key}/versions/{version}         one version, with its definition
POST /v1/document-types                                  new type, as draft v1 (admin)
POST /v1/document-types/{key}/versions                   new draft version (admin)
POST /v1/document-types/{key}/versions/{version}/publish draft -> published (admin)
POST /v1/document-types/{key}/versions/{version}/retire  published -> retired (admin)
POST /v1/document-types/proposals                        draft a new type from an example document (admin, VRT-33)
POST /v1/document-types/registrations                    register a reviewed draft: type published + its semantic
                                                         mappings as a new catalog version (admin, VRT-33)

A definition is validated by its Pydantic model (422). Publishing also
checks it against what already points at the type: every semantic mapping
of the published catalog for this type must still name a field of the new
schema (409), so a schema change cannot silently drop what the semantic
layer reads. A published version is immutable; its extractions record it."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_current_user, get_db_session, get_object_store, require_role
from idp.classification.type_from_example import DraftMapping, checked_mappings, propose_type_from_example
from idp.config import Settings
from idp.domain.document_type_catalog import DocumentTypeDefinition, FieldSpec, compile_schema
from idp.domain.semantic import FieldMapping, SemanticCatalog
from idp.persistence.models import DocumentTypeRecord, DocumentTypeVersion, User
from idp.persistence.repositories import DocumentRepository, DocumentTypeRepository, SemanticCatalogRepository, TypeSuggestionRepository
from idp.pipeline.orchestrator import parse_example
from idp.storage.object_store import S3ObjectStore

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
    document_id: str
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
            document_id=str(row.document_id),
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


# --- a new type from an example (VRT-33) -------------------------------------


class TypeProposalResponse(BaseModel):
    definition: DocumentTypeDefinition
    mappings: list[DraftMapping] = Field(description="Mapeos a atributos del catálogo semántico, ya verificados contra él.")
    dropped_mappings: list[str] = Field(description="Mapeos que propuso el modelo y el catálogo no admite, con el motivo.")
    similar_existing_type: str | None
    key_taken: bool = Field(description="Ya existe un tipo con esa clave: registrarlo exigirá otra.")
    rationale: str


class RegistrationRequest(BaseModel):
    definition: DocumentTypeDefinition
    mappings: list[DraftMapping] = Field(default_factory=list)
    suggestion_id: uuid.UUID | None = Field(default=None, description="La sugerencia aceptada que este registro resuelve.")


@admin_router.post("/proposals", response_model=TypeProposalResponse, dependencies=[Depends(require_role("admin"))])
async def propose_document_type(
    file: Annotated[UploadFile | None, File(description="Documento de ejemplo.")] = None,
    document_id: Annotated[uuid.UUID | None, Form(description="O un documento ya cargado, p. ej. el de una sugerencia aceptada.")] = None,
    name_hint: Annotated[str | None, Form(description="Cómo lo llama el usuario, si quiere orientar la propuesta.")] = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    object_store: S3ObjectStore = Depends(get_object_store),
) -> TypeProposalResponse:
    """Reads the example and drafts the whole type. Nothing is stored: the
    draft is reviewed and edited, then sent to ``/registrations``."""
    if (file is None) == (document_id is None):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="envía un archivo o un document_id, uno de los dos")
    if file is not None:
        content, filename = await file.read(), file.filename or "ejemplo"
    else:
        document = await DocumentRepository(session).get(document_id)  # type: ignore[arg-type]
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="documento no encontrado")
        content, filename = await asyncio.to_thread(object_store.get, document.storage_key), document.original_filename
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="el documento está vacío")

    repo = DocumentTypeRepository(session)
    type_catalog = await repo.load_catalog()
    active = await SemanticCatalogRepository(session).load_active()
    if active is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no hay un catálogo semántico publicado")
    parsed = await asyncio.to_thread(parse_example, settings, content, filename)
    draft = await asyncio.to_thread(
        propose_type_from_example, settings, parsed, type_catalog=type_catalog, semantic=active[0], name_hint=name_hint
    )
    definition = draft.definition()
    mappings, dropped = checked_mappings(definition, draft.mappings, active[0])
    return TypeProposalResponse(
        definition=definition,
        mappings=mappings,
        dropped_mappings=dropped,
        similar_existing_type=draft.similar_existing_type if draft.similar_existing_type in type_catalog.keys() else None,
        key_taken=await repo.get_by_key(definition.key) is not None,
        rationale=draft.rationale,
    )


@admin_router.post("/registrations", response_model=TypeVersionDetail, status_code=status.HTTP_201_CREATED)
async def register_document_type(
    body: RegistrationRequest, session: AsyncSession = Depends(get_db_session), user: User = Depends(require_role("admin"))
) -> TypeVersionDetail:
    """Publishes the reviewed type as v1 and, when it brings mappings, a new
    semantic catalog version that includes them — everything is validated
    before anything is written, so a rejected registration leaves no trace."""
    repo = DocumentTypeRepository(session)
    definition = body.definition
    if await repo.get_by_key(definition.key) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"el tipo '{definition.key}' ya existe")
    _compiles(definition)

    semantic_repo = SemanticCatalogRepository(session)
    new_catalog = None
    if body.mappings:
        active = await semantic_repo.load_active()
        if active is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no hay un catálogo semántico publicado")
        kept, dropped = checked_mappings(definition, body.mappings, active[0])
        if dropped:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=dropped)
        added = [FieldMapping(document_type=definition.key, field_path=m.field_path, attribute=m.attribute, role=m.role) for m in kept]
        try:
            new_catalog = SemanticCatalog.model_validate({**active[0].model_dump(), "mappings": [*active[0].mappings, *added]})
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"el catálogo semántico no admite los mapeos: {exc.errors()[0]['msg']}") from exc

    suggestions = TypeSuggestionRepository(session)
    if body.suggestion_id is not None and await suggestions.get(body.suggestion_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sugerencia no encontrada")

    row = await repo.create_type(definition, created_by=user.email)
    row = await repo.set_status(row, status="published", actor=user.email)
    if body.suggestion_id is not None:
        await suggestions.resolve(body.suggestion_id, decision="registered", reviewer_identity=user.email)
    if new_catalog is not None:
        draft = await semantic_repo.create_draft(new_catalog, created_by=user.email)
        await semantic_repo.publish(draft, published_by=user.email)
    await session.commit()  # the suggestion's resolution is only flushed
    return _detail(await _type_or_404(repo, definition.key), row)

