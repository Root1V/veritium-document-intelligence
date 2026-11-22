"""Checklist evaluation (VRT-27): given a case's documents, its semantic
view and the caller's process data, which of the profile's requirements
apply and which are satisfied. Pure — the caller turns the outcomes into
persisted conditions (see pipeline/case_evaluation.py).

A requirement by document type is satisfied by documents classified as that
type that did not fail. A requirement by attribute is satisfied when the
case's semantic view has the attribute for the role, from documents of an
accepted type — so alternative documents (a payslip or a debt capacity
calculation for income) satisfy the same requirement.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from idp.domain.process_profile import ChecklistItem, ProcessProfileDefinition
from idp.domain.semantic_resolution import ConsolidatedView, UnreadableEvidence
from idp.domain.verdict import ConditionKind


@dataclass(frozen=True)
class CaseDocument:
    document_id: uuid.UUID
    document_type: str | None
    status: str


class ChecklistOutcome(BaseModel):
    item: ChecklistItem
    applicable: bool
    satisfied: bool
    satisfying_document_ids: list[uuid.UUID]
    note: str | None = None
    # Unsatisfied because a document that carries it cannot be read (VRT-112):
    # the client sends a clearer copy, not another document.
    unreadable: list[UnreadableEvidence] = []

    @property
    def condition_kind(self) -> ConditionKind:
        if self.item.document_type is not None:
            return "missing_document"
        return "unreadable_evidence" if self.unreadable else "missing_evidence"


def evaluate_checklist(
    definition: ProcessProfileDefinition,
    documents: list[CaseDocument],
    view: ConsolidatedView | None,
    request_data: dict[str, Any],
) -> list[ChecklistOutcome]:
    case_cel = view.as_cel() if view is not None else {}
    return [_evaluate_item(item, documents, view, request_data, case_cel) for item in definition.checklist]


def _evaluate_item(
    item: ChecklistItem, documents: list[CaseDocument], view: ConsolidatedView | None, request_data: dict[str, Any], case_cel: dict[str, Any]
) -> ChecklistOutcome:
    if not item.required:
        return ChecklistOutcome(item=item, applicable=False, satisfied=False, satisfying_document_ids=[], note="opcional")

    note = None
    if item.required_when_cel:
        from idp.validation.cel import CelEvaluationError, compile_expression, evaluate

        try:
            applies = bool(evaluate(compile_expression(item.required_when_cel), {"request": request_data, "case": case_cel}))
        except CelEvaluationError as exc:
            # Fail closed: when the condition cannot be evaluated (e.g. a
            # field it reads is missing), the requirement is enforced.
            applies, note = True, f"required_when_cel no evaluable ({exc}); se exige por seguridad"
        if not applies:
            return ChecklistOutcome(item=item, applicable=False, satisfied=False, satisfying_document_ids=[], note="no aplica a este expediente")

    if item.document_type is not None:
        ids = [d.document_id for d in documents if d.document_type == item.document_type and d.status != "failed"]
        return ChecklistOutcome(item=item, applicable=True, satisfied=len(ids) >= item.min_count, satisfying_document_ids=ids, note=note)

    accepted = set(item.accepted_document_types) if item.accepted_document_types is not None else None
    per_attribute: list[set[uuid.UUID]] = []
    for attribute in item.requires_attributes:
        resolved = view.get(item.role, attribute) if view is not None else None
        sources = resolved.sources if resolved is not None else []
        per_attribute.append({s.document_id for s in sources if accepted is None or s.document_type in accepted})
    satisfied = all(len(ids) >= item.min_count for ids in per_attribute)
    union = sorted(set().union(*per_attribute), key=str) if per_attribute else []
    unreadable = [] if satisfied or view is None else [
        u for a in item.requires_attributes for u in view.unreadable_for(item.role, a) if accepted is None or u.document_type in accepted
    ]
    return ChecklistOutcome(item=item, applicable=True, satisfied=satisfied, satisfying_document_ids=union, note=note, unreadable=unreadable)
