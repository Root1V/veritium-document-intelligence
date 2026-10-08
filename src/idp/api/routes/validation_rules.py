"""POST /validation-rules/draft (LLM drafts a CEL condition from a
plain-language description), POST /validation-rules/manual (skip the LLM,
write CEL directly), GET /validation-rules (list, filterable by
kind/status), PATCH /validation-rules/{id} (edit a still-draft CEL rule,
re-validates CEL compiles on every edit), POST /validation-rules/{id}/activate
or /reject (kind="cel" only), POST /validation-rules/{id}/disable
(deactivates an already-active kind="cel" rule), and
GET/POST /validation-rules/toggles/* (on/off switch for the hardcoded
rule_ids from pipeline/orchestrator.py::build_default_rules), and
POST /validation-rules/{id}/test (run the rule's test cases).

VRT-36: a rule targets a document type's fields or a semantic attribute;
the draft may come back AMBIGUA (questions, nothing stored); and a rule is
activated only when every one of its test cases gives the expected outcome.

Mirrors api/routes/type_suggestions.py's exact shape and its central
guarantee: PATCH only ever touches the DB row, never generates code.
Unlike document types, though, there is no separate manual code step for
activation — the generic interpreter (validation/rules/generic.py) already
exists, so activating a row makes it execute in the very next batch run.
No row is ever hard-deleted here either — "eliminar" a rule is a status
transition (disabled/rejected), same convention as the rest of this
platform."""

from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_app_settings, get_current_user, get_db_session, require_role
from idp.config import Settings
from idp.domain.rule_draft import RuleDraft, RuleTestCase
from idp.persistence.models import User, ValidationRuleDefinition
from idp.persistence.repositories import DocumentTypeRepository, SemanticCatalogRepository, ValidationRuleRepository
from idp.pipeline.orchestrator import hardcoded_rule_metadata
from idp.validation.cel import CelCompileError, compile_expression
from idp.validation.rule_discovery import draft_rule
from idp.validation.rules.generic import TestCaseResult, run_test_cases

router = APIRouter(prefix="/validation-rules", tags=["validation-rules"], dependencies=[Depends(get_current_user)])


class ValidationRuleResponse(BaseModel):
    id: uuid.UUID
    kind: str
    rule_id: str
    category: str
    document_type: str | None
    attribute: str | None
    field_path: str | None
    description_nl: str | None
    condition_cel: str | None
    applies_when_cel: str | None
    severity: str | None
    message_pass: str | None
    message_fail: str | None
    rationale: str | None
    status: str
    created_by: str | None
    reviewer_identity: str | None
    test_cases: list[RuleTestCase]


def _to_response(row: ValidationRuleDefinition) -> ValidationRuleResponse:
    return ValidationRuleResponse(
        id=row.id,
        kind=row.kind,
        rule_id=row.rule_id,
        category=row.category,
        document_type=row.document_type,
        attribute=row.attribute,
        field_path=row.field_path,
        description_nl=row.description_nl,
        condition_cel=row.condition_cel,
        applies_when_cel=row.applies_when_cel,
        severity=row.severity,
        message_pass=row.message_pass,
        message_fail=row.message_fail,
        rationale=row.rationale,
        status=row.status,
        created_by=row.created_by,
        reviewer_identity=row.reviewer_identity,
        test_cases=[RuleTestCase.model_validate(c) for c in row.test_cases or []],
    )


def _validate_cel_or_400(condition_cel: str, applies_when_cel: str | None) -> None:
    try:
        compile_expression(condition_cel)
        if applies_when_cel:
            compile_expression(applies_when_cel)
    except CelCompileError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"expresion CEL invalida: {exc}") from exc


class RuleTarget(BaseModel):
    document_type: str | None = None
    attribute: str | None = None

    @model_validator(mode="after")
    def _one_target(self) -> RuleTarget:
        if (self.document_type is None) == (self.attribute is None):
            raise ValueError("una regla es sobre un tipo de documento o sobre un atributo: indica uno de los dos")
        return self

    @property
    def scope(self) -> str:
        return self.document_type or self.attribute  # type: ignore[return-value]


class DraftRuleRequest(RuleTarget):
    description: str
    category: Literal["self", "request_input", "reference_data"]
    field_path: str | None = None
    existing_fields_hint: list[str] | None = None

    @field_validator("description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description cannot be blank")
        return value


class ManualRuleRequest(RuleTarget):
    """The 'skip the LLM' power-user path — a human types CEL directly."""

    rule_id_suffix: str
    category: Literal["self", "request_input", "reference_data"]
    field_path: str | None = None
    condition_cel: str
    applies_when_cel: str | None = None
    severity: Literal["info", "warning", "error"]
    message_pass: str
    message_fail: str
    rationale: str | None = None
    test_cases: list[RuleTestCase] = []


class DraftRuleResponse(BaseModel):
    outcome: Literal["ok", "ambiguous"]
    questions: list[str]
    rule: ValidationRuleResponse | None = None


@router.post("/draft", response_model=DraftRuleResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def draft_new_rule(
    body: DraftRuleRequest,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> DraftRuleResponse:
    """An AMBIGUA draft stores nothing: it returns the questions that would
    resolve it, to refine the description and ask again."""
    active = await SemanticCatalogRepository(session).load_active()
    if body.attribute is not None and (active is None or body.attribute not in {a.key for a in active[0].attributes}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"el atributo '{body.attribute}' no está en el catálogo semántico publicado")
    proposal: RuleDraft = await asyncio.to_thread(
        draft_rule,
        settings,
        description=body.description,
        document_type=body.document_type,
        attribute=body.attribute,
        category=body.category,
        field_path=body.field_path,
        existing_fields_hint=body.existing_fields_hint,
        semantic=active[0] if active else None,
    )
    if proposal.outcome == "ambiguous":
        return DraftRuleResponse(outcome="ambiguous", questions=proposal.questions)
    _validate_cel_or_400(proposal.condition_cel, proposal.applies_when_cel)  # type: ignore[arg-type]

    repo = ValidationRuleRepository(session)
    rule_id = f"custom.{body.scope}.{uuid.uuid4().hex[:8]}"
    row = await repo.create_cel_draft(
        rule_id=rule_id,
        category=body.category,
        document_type=body.document_type,
        attribute=body.attribute,
        test_cases=[c.model_dump(mode="json") for c in proposal.test_cases],
        field_path=body.field_path,
        description_nl=body.description,
        condition_cel=proposal.condition_cel,
        applies_when_cel=proposal.applies_when_cel,
        severity=proposal.severity,
        message_pass=proposal.message_pass,
        message_fail=proposal.message_fail,
        rationale=proposal.rationale,
        created_by=current_user.name,
    )
    await session.commit()
    return DraftRuleResponse(outcome="ok", questions=[], rule=_to_response(row))


@router.post("/manual", response_model=ValidationRuleResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def create_manual_rule(
    body: ManualRuleRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ValidationRuleResponse:
    _validate_cel_or_400(body.condition_cel, body.applies_when_cel)
    repo = ValidationRuleRepository(session)
    rule_id = f"custom.{body.scope}.{body.rule_id_suffix}"
    if await repo.get_by_rule_id(rule_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="rule_id already exists")
    row = await repo.create_cel_draft(
        rule_id=rule_id,
        category=body.category,
        document_type=body.document_type,
        attribute=body.attribute,
        test_cases=[c.model_dump(mode="json") for c in body.test_cases],
        field_path=body.field_path,
        description_nl=None,
        condition_cel=body.condition_cel,
        applies_when_cel=body.applies_when_cel,
        severity=body.severity,
        message_pass=body.message_pass,
        message_fail=body.message_fail,
        rationale=body.rationale,
        created_by=current_user.name,
    )
    await session.commit()
    return _to_response(row)


@router.get("", response_model=list[ValidationRuleResponse])
async def list_rules(
    kind: str | None = None,
    status_filter: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[ValidationRuleResponse]:
    repo = ValidationRuleRepository(session)
    rows = await (repo.list_by_status(status_filter, kind=kind) if status_filter else repo.list_all(kind=kind))
    return [_to_response(row) for row in rows]


class UpdateRuleRequest(BaseModel):
    condition_cel: str | None = None
    applies_when_cel: str | None = None
    severity: Literal["info", "warning", "error"] | None = None
    message_pass: str | None = None
    message_fail: str | None = None
    field_path: str | None = None
    test_cases: list[RuleTestCase] | None = None


@router.patch("/{definition_id}", response_model=ValidationRuleResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def update_rule(
    definition_id: uuid.UUID,
    body: UpdateRuleRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ValidationRuleResponse:
    repo = ValidationRuleRepository(session)
    row = await repo.get(definition_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    if row.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only a draft rule can be edited")

    effective_condition = body.condition_cel if body.condition_cel is not None else row.condition_cel
    effective_gate = body.applies_when_cel if body.applies_when_cel is not None else row.applies_when_cel
    if effective_condition is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="condition_cel is required")
    _validate_cel_or_400(effective_condition, effective_gate)

    row = await repo.update_draft(
        definition_id,
        condition_cel=body.condition_cel,
        applies_when_cel=body.applies_when_cel,
        severity=body.severity,
        message_pass=body.message_pass,
        message_fail=body.message_fail,
        field_path=body.field_path,
        test_cases=[c.model_dump(mode="json") for c in body.test_cases] if body.test_cases is not None else None,
    )
    await session.commit()
    return _to_response(row)


async def _results(session: AsyncSession, row: ValidationRuleDefinition) -> list[TestCaseResult]:
    """The rule's test cases, typed as the run would see them: the
    attribute's data type, or the document type's field types."""
    value_type, field_types = None, None
    if row.attribute is not None:
        active = await SemanticCatalogRepository(session).load_active()
        value_type = next((a.data_type for a in active[0].attributes if a.key == row.attribute), None) if active else None
    elif row.document_type is not None:
        current = (await DocumentTypeRepository(session).load_catalog()).current(row.document_type)
        field_types = {f.name: f.type for f in current[1].fields} if current else None
    cases = [RuleTestCase.model_validate(c) for c in row.test_cases or []]
    return run_test_cases(row.condition_cel or "true", row.applies_when_cel, cases, value_type=value_type, field_types=field_types)


async def _test_problems(session: AsyncSession, row: ValidationRuleDefinition) -> list[str]:
    """Why a rule cannot be activated yet: it needs a case that passes and
    one that fails, and every case must give its expected outcome."""
    cases = [RuleTestCase.model_validate(c) for c in row.test_cases or []]
    if {c.expect for c in cases} != {"pass", "fail"}:
        return ["la regla necesita al menos un caso de prueba que cumpla ('pass') y uno que no ('fail')"]
    return [
        f"caso '{r.name}': se esperaba {r.expect} y dio {r.got}" + (f" ({r.detail})" if r.detail else "")
        for r in await _results(session, row)
        if not r.ok
    ]


class TestRunResponse(BaseModel):
    results: list[TestCaseResult]
    all_ok: bool


async def _resolve(definition_id: uuid.UUID, decision: str, reviewer_identity: str, session: AsyncSession) -> ValidationRuleResponse:
    repo = ValidationRuleRepository(session)
    row = await repo.get(definition_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    if row.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only a draft rule can be activated or rejected")
    if decision == "active":
        if row.condition_cel is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="condition_cel is required")
        _validate_cel_or_400(row.condition_cel, row.applies_when_cel)  # defense in depth — should already be valid
        problems = await _test_problems(session, row)
        if problems:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=problems)
    row = await repo.set_status(definition_id, status=decision, reviewer_identity=reviewer_identity)
    await session.commit()
    return _to_response(row)


@router.post("/{definition_id}/test", response_model=TestRunResponse)
async def run_rule_tests(definition_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> TestRunResponse:
    row = await ValidationRuleRepository(session).get(definition_id)
    if row is None or row.kind != "cel":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    results = await _results(session, row)
    return TestRunResponse(results=results, all_ok=bool(results) and all(r.ok for r in results))


@router.post("/{definition_id}/activate", response_model=ValidationRuleResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def activate_rule(
    definition_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ValidationRuleResponse:
    return await _resolve(definition_id, "active", current_user.name, session)


@router.post("/{definition_id}/reject", response_model=ValidationRuleResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def reject_rule(
    definition_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ValidationRuleResponse:
    return await _resolve(definition_id, "rejected", current_user.name, session)


@router.post("/{definition_id}/disable", response_model=ValidationRuleResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def disable_active_rule(
    definition_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ValidationRuleResponse:
    repo = ValidationRuleRepository(session)
    row = await repo.get(definition_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    if row.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only an active rule can be disabled")
    row = await repo.set_status(definition_id, status="disabled", reviewer_identity=current_user.name)
    await session.commit()
    return _to_response(row)


# --- Toggle endpoints for the hardcoded rule_ids ----------------------------


class ToggleRuleResponse(BaseModel):
    rule_id: str
    category: str
    description: str
    status: str  # "active" | "disabled"


@router.get("/toggles", response_model=list[ToggleRuleResponse])
async def list_toggles(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> list[ToggleRuleResponse]:
    repo = ValidationRuleRepository(session)
    existing = {row.rule_id: row for row in await repo.list_all(kind="toggle")}
    return [
        ToggleRuleResponse(
            rule_id=rule_id,
            category=category,
            description=description,
            status=existing[rule_id].status if rule_id in existing else "active",
        )
        for rule_id, category, description in hardcoded_rule_metadata(settings)
    ]


async def _set_toggle(rule_id: str, decision: str, settings: Settings, session: AsyncSession, current_user: User) -> ToggleRuleResponse:
    metadata = {rid: (category, description) for rid, category, description in hardcoded_rule_metadata(settings)}
    if rule_id not in metadata:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown hardcoded rule_id")
    category, description = metadata[rule_id]
    repo = ValidationRuleRepository(session)
    row = await repo.get_or_create_toggle(rule_id=rule_id, category=category)
    row = await repo.set_status(row.id, status=decision, reviewer_identity=current_user.name)
    await session.commit()
    return ToggleRuleResponse(rule_id=row.rule_id, category=row.category, description=description, status=row.status)


@router.post("/toggles/{rule_id:path}/disable", response_model=ToggleRuleResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def disable_hardcoded_rule(
    rule_id: str,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ToggleRuleResponse:
    return await _set_toggle(rule_id, "disabled", settings, session, current_user)


@router.post("/toggles/{rule_id:path}/enable", response_model=ToggleRuleResponse, dependencies=[Depends(require_role("operador", "admin"))])
async def enable_hardcoded_rule(
    rule_id: str,
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ToggleRuleResponse:
    return await _set_toggle(rule_id, "active", settings, session, current_user)
