"""Case-level evaluation under its process profile (VRT-27): which rules
run and with what weight, the checklist turned into conditions, and the
verdict. ``refresh_verdict`` is the single place a verdict is computed — a
run calls it at the end, and so does every human action that changes the
case state without a new run (waiving a condition, resolving a review)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from idp.domain.completeness import CaseDocument, ChecklistOutcome, attestations_of, evaluate_checklist
from idp.domain.process_profile import ProcessProfileDefinition
from idp.domain.semantic_resolution import ConsolidatedView
from idp.domain.verdict import CaseVerdict, FindingInput, OpenCondition, VerdictInputs, decide
from idp.persistence.models import Case, CaseCondition, CaseRun
from idp.persistence.repositories import CaseConditionRepository, CaseRepository, DocumentRepository, ReviewRepository, ValidationRepository
from idp.validation.base import ValidationResult, ValidationRule
from idp.webhooks.events import emit_verdict_changed


def profile_definition(case: Case) -> ProcessProfileDefinition | None:
    """None for cases created before VRT-25 (no pinned profile): they are
    evaluated like the built-in ad-hoc profile."""
    if case.profile_version is None:
        return None
    return ProcessProfileDefinition.model_validate(case.profile_version.definition)


def rules_for_profile(rules: list[ValidationRule], definition: ProcessProfileDefinition | None) -> list[ValidationRule]:
    """Only the rules the profile binds — unless it includes all of them
    (ad-hoc) or there is no profile."""
    if definition is None or definition.include_all_rules:
        return rules
    bound = definition.bound_rule_ids()
    return [r for r in rules if r.rule_id in bound]


def apply_binding(result: ValidationResult, definition: ProcessProfileDefinition | None) -> ValidationResult:
    """The severity of a failed rule is the one its binding declares."""
    if definition is None or result.passed:
        return result
    binding = definition.binding_for(result.rule_id)
    return result.model_copy(update={"severity": binding.severity}) if binding is not None else result


_WHY = {"blurry": "borroso", "cut_off": "cortado en el borde", "covered": "tapado", "illegible_handwriting": "letra a mano ilegible", "other": "no se distingue"}


def _unreadable_note(outcome: ChecklistOutcome) -> str | None:
    """Where it cannot be read, for the person who asks the client again: 'pág. 2, borroso'."""
    if not outcome.unreadable:
        return outcome.note
    u = outcome.unreadable[0]
    return ", ".join(p for p in (f"pág. {u.page + 1}" if u.page is not None else None, _WHY.get(u.why, u.why)) if p)


async def refresh_conditions(
    session: AsyncSession, case: Case, run: CaseRun, view: ConsolidatedView | None, definition: ProcessProfileDefinition | None
) -> None:
    """Open a condition for every applicable, unsatisfied requirement;
    close the open ones a run finds satisfied or no longer applicable.
    A waived condition stays waived."""
    if definition is None or not definition.checklist:
        return
    documents = [
        CaseDocument(document_id=d.id, document_type=d.document_type, status=d.status, attestations=attestations_of(d.extraction.payload if d.extraction else None))
        for d in await DocumentRepository(session).list_for_case(case.id)
    ]
    repo = CaseConditionRepository(session)
    latest = await repo.latest_by_key(case.id)
    for outcome in evaluate_checklist(definition, documents, view, case.request_input_payload or {}):
        item, current = outcome.item, latest.get(outcome.item.key)
        if outcome.applicable and not outcome.satisfied:
            if current is not None and (current.status == "waived" or (current.status == "open" and current.kind == outcome.condition_kind)):
                continue
            if current is not None and current.status == "open":  # same requirement, now known to be there but unreadable, or the reverse
                await repo.resolve(current, run_id=run.id, document_id=None, note="Cambió el motivo")
            unreadable = outcome.unreadable[0] if outcome.unreadable else None
            await repo.add(
                CaseCondition(
                    case_id=case.id,
                    key=item.key,
                    label=item.label,
                    kind=outcome.condition_kind,
                    # Unreadable: the document to send again (VRT-112).
                    document_type=unreadable.document_type if unreadable else item.document_type,
                    attributes=item.requires_attributes or None,
                    role=item.role if item.requires_attributes else None,
                    note=_unreadable_note(outcome),
                    opened_in_run_id=run.id,
                )
            )
        elif current is not None and current.status == "open":
            if outcome.satisfied:
                await repo.resolve(
                    current,
                    run_id=run.id,
                    document_id=outcome.satisfying_document_ids[0] if outcome.satisfying_document_ids else None,
                    note="Documento recibido" if item.document_type is not None else "Evidencia recibida",
                )
            else:
                await repo.resolve(current, run_id=run.id, document_id=None, note=outcome.note or "Ya no aplica")


async def refresh_verdict(session: AsyncSession, case_id: uuid.UUID, *, run: CaseRun | None = None) -> CaseVerdict:
    case = await CaseRepository(session).get(case_id)
    if case is None:
        raise ValueError(f"case not found: {case_id}")
    conditions = await CaseConditionRepository(session).list_for_case(case_id)
    issues = await ValidationRepository(session).list_for_case(case_id)
    documents = await DocumentRepository(session).list_for_case(case_id)
    inputs = VerdictInputs(
        open_conditions=[OpenCondition(key=c.key, label=c.label, kind=c.kind) for c in conditions if c.status == "open"],  # type: ignore[arg-type]
        findings=[FindingInput(rule_id=i.rule_id, message=i.message, document_id=i.document_id) for i in issues],
        pending_review_document_ids=await ReviewRepository(session).pending_document_ids_for_case(case_id),
        failed_document_ids={d.id for d in documents if d.status == "failed"},
    )
    verdict = decide(inputs, profile_definition(case))
    reasons = [r.model_dump(mode="json") for r in verdict.reasons]
    previous = case.verdict
    case.verdict, case.verdict_reasons, case.verdict_at = verdict.decision, reasons, datetime.now(UTC)
    if verdict.decision != previous:
        # Same transaction as the change (outbox, VRT-28).
        emit_verdict_changed(session, case, previous=previous, reason_kinds=sorted({r.kind for r in verdict.reasons}))
    if run is not None:
        run.verdict, run.verdict_reasons = verdict.decision, reasons
    return verdict
