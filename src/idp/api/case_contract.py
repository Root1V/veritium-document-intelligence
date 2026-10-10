"""Case result contract v1 (VRT-25, ADR-0005) — what ``GET /v1/cases/{id}/result``
returns, and the canonical source every other format will be derived from
(YAML / Markdown / PDF in VRT-41, A2UI in VRT-50). Additive changes (new
optional fields) keep v1; anything incompatible is v2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.domain.semantic_resolution import ResolvedAttribute
from idp.domain.verdict import VerdictReason
from idp.persistence.models import Case, CaseCondition, CaseRun
from idp.persistence.repositories import CaseConditionRepository, DocumentRepository, ValidationRepository
from idp.pipeline.orchestrator import case_document_fields, resolve_semantic_view


class ProfileRef(BaseModel):
    key: str
    version: int
    content_hash: str
    semantic_catalog_version: int


class CaseInfo(BaseModel):
    id: uuid.UUID
    external_ref: str | None
    channel: str
    status: str
    profile: ProfileRef | None
    created_at: datetime


class Verdict(BaseModel):
    """What the calling process should do next (VRT-27). Null decision only
    for a case whose first run has not finished."""

    decision: Literal["continue", "human_review", "return_to_client"] | None
    reasons: list[VerdictReason]
    decided_at: datetime | None


class ConditionResult(BaseModel):
    """A required document or evidence the case is (or was) missing."""

    id: uuid.UUID
    key: str
    label: str
    kind: str
    document_type: str | None
    attributes: list[str] | None
    role: str | None
    status: Literal["open", "resolved", "waived"]
    note: str | None
    resolved_by_document_id: uuid.UUID | None
    waived_by: str | None
    waived_reason: str | None
    opened_at: datetime
    resolved_at: datetime | None


def condition_result(c: CaseCondition) -> ConditionResult:
    return ConditionResult(
        id=c.id,
        key=c.key,
        label=c.label,
        kind=c.kind,
        document_type=c.document_type,
        attributes=c.attributes,
        role=c.role,
        status=c.status,  # type: ignore[arg-type]
        note=c.note,
        resolved_by_document_id=c.resolved_by_document_id,
        waived_by=c.waived_by,
        waived_reason=c.waived_reason,
        opened_at=c.opened_at,
        resolved_at=c.resolved_at,
    )


class DocumentResult(BaseModel):
    id: uuid.UUID
    filename: str
    document_type: str | None
    status: str
    needs_review: bool
    parent_document_id: uuid.UUID | None
    page_start: int | None
    page_end: int | None
    # Extracted[T] envelopes as stored: value + page + bbox + confidence + source_text.
    fields: dict[str, Any] | None


class Finding(BaseModel):
    id: uuid.UUID  # what an investigation of it refers to (VRT-66)
    rule_id: str
    category: str
    severity: str
    document_id: uuid.UUID | None
    field_path: str | None
    message: str
    expected: Any
    actual: Any
    confidence: float
    confidence_method: str
    explanation: str


class RunInfo(BaseModel):
    run_number: int
    trigger: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    # What a reprocess run redid (VRT-40); None for a full run.
    scope: dict[str, Any] | None
    # Rule versions live here (provenance.rules): a finding's rule_id
    # resolves to the exact definition that produced it.
    provenance: dict[str, Any] | None


class CaseResultV1(BaseModel):
    contract_version: Literal["1"] = "1"
    case: CaseInfo
    verdict: Verdict
    conditions: list[ConditionResult]
    semantic_catalog_version: int | None
    entities: dict[str, dict[str, dict[str, ResolvedAttribute]]]
    documents: list[DocumentResult]
    findings: list[Finding]
    run: RunInfo | None


def profile_ref(case: Case) -> ProfileRef | None:
    pv = case.profile_version
    if pv is None:
        return None
    return ProfileRef(key=pv.profile.key, version=pv.version, content_hash=pv.content_hash, semantic_catalog_version=pv.semantic_catalog_version)


def latest_run(case: Case) -> CaseRun | None:
    return max(case.runs, key=lambda r: r.run_number) if case.runs else None


async def build_case_result(session: AsyncSession, case: Case) -> CaseResultV1:
    documents = await DocumentRepository(session).list_for_case(case.id)
    fields = await case_document_fields(DocumentRepository(session), case.id)
    catalog_version = case.profile_version.semantic_catalog_version if case.profile_version is not None else None
    view = await resolve_semantic_view(session, fields, catalog_version=catalog_version)
    issues = await ValidationRepository(session).list_for_case(case.id)
    run = latest_run(case)
    return CaseResultV1(
        case=CaseInfo(
            id=case.id, external_ref=case.external_ref, channel=case.channel, status=case.status, profile=profile_ref(case), created_at=case.created_at
        ),
        verdict=Verdict(decision=case.verdict, reasons=[VerdictReason.model_validate(r) for r in case.verdict_reasons or []], decided_at=case.verdict_at),  # type: ignore[arg-type]
        conditions=[condition_result(c) for c in await CaseConditionRepository(session).list_for_case(case.id)],
        semantic_catalog_version=view.catalog_version if view else None,
        entities=view.nested() if view else {},
        documents=[
            DocumentResult(
                id=d.id,
                filename=d.original_filename,
                document_type=d.document_type,
                status=d.status,
                needs_review=d.needs_review,
                parent_document_id=d.parent_document_id,
                page_start=d.page_start,
                page_end=d.page_end,
                fields=d.extraction.payload if d.extraction is not None else None,
            )
            for d in sorted(documents, key=lambda d: d.created_at)
        ],
        findings=[
            Finding(
                id=i.id,
                rule_id=i.rule_id,
                category=i.category,
                severity=i.severity,
                document_id=i.document_id,
                field_path=i.field_path,
                message=i.message,
                expected=i.expected,
                actual=i.actual,
                confidence=i.confidence,
                confidence_method=i.confidence_method,
                explanation=i.explanation,
            )
            for i in issues
        ],
        run=RunInfo(
            run_number=run.run_number,
            trigger=run.trigger,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error=run.error,
            scope=run.scope,
            provenance=run.provenance,
        )
        if run is not None
        else None,
    )
