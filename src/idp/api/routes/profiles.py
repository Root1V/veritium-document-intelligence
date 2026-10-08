"""Process profile administration (VRT-24).

GET  /v1/profiles                                  all profiles, with their active (latest published) version
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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_current_user, get_db_session, require_role
from idp.config import Settings
from idp.domain.process_profile import ProcessProfileDefinition, cross_reference_errors
from idp.domain.semantic import SemanticCatalog
from idp.persistence.models import ProcessProfile, ProcessProfileVersion, User
from idp.persistence.repositories import DocumentTypeRepository, ProcessProfileRepository, SemanticCatalogRepository, ValidationRuleRepository
from idp.pipeline.orchestrator import hardcoded_rule_metadata

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
    errors = cross_reference_errors(
        definition,
        catalog=SemanticCatalog.model_validate(catalog_row.definition),
        known_document_types=set((await DocumentTypeRepository(session).load_catalog()).keys()),
        known_rule_ids=await _known_rule_ids(session, settings),
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
