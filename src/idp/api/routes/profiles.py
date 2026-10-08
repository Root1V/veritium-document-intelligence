"""Process profile administration (VRT-24).

GET  /v1/profiles                                  all profiles, with their active (latest published) version
GET  /v1/profiles/library                         what a profile can be built from (VRT-37), with what other profiles use
GET  /v1/profiles/{key}                            one profile and its versions (summary)
GET  /v1/profiles/{key}/versions/{version}         one version, with its definition
POST /v1/profiles                                  new profile (admin)
POST /v1/profiles/{key}/versions                   new draft version (admin)
POST /v1/profiles/{key}/versions/{version}/publish draft -> published (admin)
POST /v1/profiles/{key}/versions/{version}/retire  published -> retired (admin)

A definition is validated twice on the way in: intrinsically by its Pydantic
model (422) and against what it references — the pinned semantic catalog
version, document types, roles, attributes and rule ids (400). Published
versions are immutable. The web designer is F2 (VRT-37)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_current_user, get_db_session, require_role
from idp.config import Settings
from idp.domain.process_profile import LEGACY_RULE_IDS, ProcessProfileDefinition, cross_reference_errors
from idp.domain.semantic import SemanticCatalog
from idp.persistence.models import ProcessProfile, ProcessProfileVersion, User
from idp.persistence.repositories import DocumentTypeRepository, ProcessProfileRepository, SemanticCatalogRepository, ValidationRuleRepository
from idp.pipeline.orchestrator import hardcoded_rule_metadata
from idp.validation.rules.semantic_rules import format_rule_id, format_rules

router = APIRouter(prefix="/v1/profiles", tags=["profiles"], dependencies=[Depends(get_current_user)])

_PROFILE_KEY = re.compile(r"^[a-z][a-z0-9-]*$")


class ProfileVersionSummary(BaseModel):
    version: int
    status: str
    content_hash: str
    semantic_catalog_version: int
    created_by: str | None
    created_at: datetime
    published_by: str | None
    published_at: datetime | None
    retired_at: datetime | None


class ProfileVersionDetail(ProfileVersionSummary):
    profile_key: str
    definition: ProcessProfileDefinition


class ProfileResponse(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    active_version: int | None
    versions: list[ProfileVersionSummary]


class CreateProfileRequest(BaseModel):
    key: str = Field(description="Identificador estable, en minúsculas con guiones, p. ej. 'contratacion-tarjetas'.")
    name: str
    description: str | None = None

    @field_validator("key")
    @classmethod
    def _key_format(cls, value: str) -> str:
        if not _PROFILE_KEY.match(value):
            raise ValueError("la clave debe empezar con una letra y usar solo minúsculas, dígitos y '-'")
        return value


def _summary(v: ProcessProfileVersion) -> ProfileVersionSummary:
    return ProfileVersionSummary(
        version=v.version,
        status=v.status,
        content_hash=v.content_hash,
        semantic_catalog_version=v.semantic_catalog_version,
        created_by=v.created_by,
        created_at=v.created_at,
        published_by=v.published_by,
        published_at=v.published_at,
        retired_at=v.retired_at,
    )


def _detail(profile: ProcessProfile, v: ProcessProfileVersion) -> ProfileVersionDetail:
    return ProfileVersionDetail(**_summary(v).model_dump(), profile_key=profile.key, definition=ProcessProfileDefinition.model_validate(v.definition))


def _profile(profile: ProcessProfile) -> ProfileResponse:
    active = ProcessProfileRepository.latest_published(profile)
    return ProfileResponse(
        id=profile.id,
        key=profile.key,
        name=profile.name,
        description=profile.description,
        active_version=active.version if active else None,
        versions=[_summary(v) for v in profile.versions],
    )


async def _profile_or_404(repo: ProcessProfileRepository, key: str) -> ProcessProfile:
    profile = await repo.get_by_key(key)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"profile '{key}' not found")
    return profile


async def _version_or_404(repo: ProcessProfileRepository, profile: ProcessProfile, version: int) -> ProcessProfileVersion:
    row = await repo.get_version(profile, version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"version {version} of '{profile.key}' not found")
    return row


@router.get("", response_model=list[ProfileResponse])
async def list_profiles(session: AsyncSession = Depends(get_db_session)) -> list[ProfileResponse]:
    return [_profile(p) for p in await ProcessProfileRepository(session).list_profiles()]


class LibraryDocumentType(BaseModel):
    key: str
    display_name: str
    used_by: list[str]


class LibraryAttribute(BaseModel):
    key: str
    name: str
    data_type: str
    providers: list[dict[str, str]] = Field(description="[{document_type, role}] que mapean el atributo en esta versión del catálogo.")
    used_by: list[str]


class LibraryRule(BaseModel):
    rule_id: str
    kind: Literal["code", "cel", "format"]
    description: str
    document_type: str | None = None
    attribute: str | None = None
    applies_to: list[str] = Field(description="Tipos de documento sobre los que corre; vacío = no se sabe de antemano (reglas de código).")
    used_by: list[str]


class ProfileLibrary(BaseModel):
    catalog_version: int
    catalog_versions: list[int]
    document_types: list[LibraryDocumentType]
    attributes: list[LibraryAttribute]
    roles: list[dict[str, str]]
    rules: list[LibraryRule]
    legacy_rule_ids: dict[str, str] = Field(description="Ids retirados → el que los reemplaza; una versión nueva usa el nuevo (VRT-35).")


@router.get("/library", response_model=ProfileLibrary)
async def profile_library(
    catalog_version: int | None = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> ProfileLibrary:
    """Everything a profile can reference for one semantic catalog version,
    each with the profiles whose active version already uses it — the
    designer's suggestions are reuse, not invention."""
    catalog_repo = SemanticCatalogRepository(session)
    published = [v.version for v in await catalog_repo.list_versions() if v.status == "published"]
    version = catalog_version or (max(published) if published else None)
    row = await catalog_repo.get_version(version) if version is not None else None
    if row is None or row.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"el catálogo semántico v{catalog_version} no existe o no está publicado")
    catalog = SemanticCatalog.model_validate(row.definition)

    active: dict[str, ProcessProfileDefinition] = {}
    for profile in await ProcessProfileRepository(session).list_profiles():
        current = ProcessProfileRepository.latest_published(profile)
        if current is not None:
            active[profile.key] = ProcessProfileDefinition.model_validate(current.definition)

    def using(predicate) -> list[str]:  # noqa: ANN001
        return sorted(k for k, d in active.items() if predicate(d))

    types = await DocumentTypeRepository(session).load_catalog()
    providers: dict[str, list[dict[str, str]]] = {}
    for m in catalog.mappings:
        providers.setdefault(m.attribute, []).append({"document_type": m.document_type, "role": m.role})
    doc_types_of = {a: sorted({p["document_type"] for p in ps}) for a, ps in providers.items()}

    rules = [
        LibraryRule(rule_id=rule_id, kind="code", description=description, applies_to=[], used_by=using(lambda d, r=rule_id: r in d.bound_rule_ids()))
        for rule_id, _, description in hardcoded_rule_metadata(settings)
    ]
    rules += [
        LibraryRule(
            rule_id=f, kind="format", description=f"Formato de {a.name}: {a.format_cel}", attribute=a.key,
            applies_to=doc_types_of.get(a.key, []), used_by=using(lambda d, r=f: r in d.bound_rule_ids()),
        )
        for a in catalog.attributes
        if a.format_cel
        for f in [format_rule_id(a.key)]
    ]
    for cel in await ValidationRuleRepository(session).list_all(kind="cel"):
        if cel.status in ("rejected", "disabled"):
            continue
        rules.append(LibraryRule(
            rule_id=cel.rule_id, kind="cel", description=cel.description_nl or cel.rationale or (cel.condition_cel or ""),
            document_type=cel.document_type, attribute=cel.attribute,
            applies_to=[cel.document_type] if cel.document_type else doc_types_of.get(cel.attribute or "", []),
            used_by=using(lambda d, r=cel.rule_id: r in d.bound_rule_ids()),
        ))

    return ProfileLibrary(
        catalog_version=row.version,
        catalog_versions=sorted(published),
        document_types=[
            LibraryDocumentType(key=k, display_name=types.current(k)[1].display_name,  # type: ignore[index]
                                used_by=using(lambda d, k=k: any(i.document_type == k for i in d.checklist)))
            for k in types.keys()
        ],
        attributes=[
            LibraryAttribute(key=a.key, name=a.name, data_type=a.data_type, providers=providers.get(a.key, []),
                             used_by=using(lambda d, k=a.key: any(k in i.requires_attributes for i in d.checklist)))
            for a in catalog.attributes
        ],
        roles=[{"key": r.key, "name": r.name} for r in catalog.roles],
        rules=rules,
        legacy_rule_ids=LEGACY_RULE_IDS,
    )


@router.get("/{key}", response_model=ProfileResponse)
async def get_profile(key: str, session: AsyncSession = Depends(get_db_session)) -> ProfileResponse:
    return _profile(await _profile_or_404(ProcessProfileRepository(session), key))


@router.get("/{key}/versions/{version}", response_model=ProfileVersionDetail)
async def get_profile_version(key: str, version: int, session: AsyncSession = Depends(get_db_session)) -> ProfileVersionDetail:
    repo = ProcessProfileRepository(session)
    profile = await _profile_or_404(repo, key)
    return _detail(profile, await _version_or_404(repo, profile, version))


@router.post("", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: CreateProfileRequest,
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_role("admin")),
) -> ProfileResponse:
    repo = ProcessProfileRepository(session)
    if await repo.get_by_key(body.key) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"profile '{body.key}' already exists")
    return _profile(await repo.create_profile(key=body.key, name=body.name, description=body.description))


@router.post("/{key}/versions", response_model=ProfileVersionDetail, status_code=status.HTTP_201_CREATED)
async def create_profile_draft(
    key: str,
    definition: ProcessProfileDefinition,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(require_role("admin")),
) -> ProfileVersionDetail:
    repo = ProcessProfileRepository(session)
    profile = await _profile_or_404(repo, key)

    catalog_row = await SemanticCatalogRepository(session).get_version(definition.semantic_catalog_version)
    if catalog_row is None or catalog_row.status != "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=[f"el catálogo semántico v{definition.semantic_catalog_version} no existe o no está publicado"],
        )
    catalog = SemanticCatalog.model_validate(catalog_row.definition)
    errors = cross_reference_errors(
        definition,
        catalog=catalog,
        known_document_types=set((await DocumentTypeRepository(session).load_catalog()).keys()),
        # + one format rule per attribute of the pinned catalog that declares a format (VRT-35)
        known_rule_ids=await _known_rule_ids(session, settings) | {r.rule_id for r in format_rules(catalog)},
    )
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors)
    return _detail(profile, await repo.create_draft(profile, definition, created_by=user.email))


@router.post("/{key}/versions/{version}/publish", response_model=ProfileVersionDetail)
async def publish_profile_version(
    key: str, version: int, session: AsyncSession = Depends(get_db_session), user: User = Depends(require_role("admin"))
) -> ProfileVersionDetail:
    return await _transition(session, key, version, from_status="draft", to_status="published", actor=user.email)


@router.post("/{key}/versions/{version}/retire", response_model=ProfileVersionDetail)
async def retire_profile_version(
    key: str, version: int, session: AsyncSession = Depends(get_db_session), user: User = Depends(require_role("admin"))
) -> ProfileVersionDetail:
    return await _transition(session, key, version, from_status="published", to_status="retired", actor=user.email)


async def _transition(session: AsyncSession, key: str, version: int, *, from_status: str, to_status: str, actor: str) -> ProfileVersionDetail:
    repo = ProcessProfileRepository(session)
    profile = await _profile_or_404(repo, key)
    row = await _version_or_404(repo, profile, version)
    if row.status != from_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"version {version} is {row.status}; only a {from_status} version can become {to_status}",
        )
    return _detail(profile, await repo.set_status(row, status=to_status, actor=actor))


async def _known_rule_ids(session: AsyncSession, settings: Settings) -> set[str]:
    """Every rule a profile may bind: the hardcoded set (including the
    semantic consistency rule) plus every data-driven CEL rule that was not
    rejected — a draft may be bound before it is activated."""
    hardcoded = {rule_id for rule_id, _, _ in hardcoded_rule_metadata(settings)}
    cel = {row.rule_id for row in await ValidationRuleRepository(session).list_all(kind="cel") if row.status != "rejected"}
    return hardcoded | cel
