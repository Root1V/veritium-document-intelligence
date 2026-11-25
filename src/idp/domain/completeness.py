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

from idp.domain.attestation import Attestations
from idp.domain.process_profile import ChecklistItem, ProcessProfileDefinition
from idp.domain.semantic_resolution import ConsolidatedView, UnreadableEvidence
from idp.domain.verdict import ConditionKind


@dataclass(frozen=True)
class CaseDocument:
    document_id: uuid.UUID
    document_type: str | None
    status: str
    attestations: Attestations | None = None  # VRT-118


def attestations_of(payload: dict | None) -> Attestations | None:
    found = (payload or {}).get("attestations")
    return Attestations.model_validate(found) if found else None


class ChecklistOutcome(BaseModel):
    item: ChecklistItem
    applicable: bool
    satisfied: bool
    satisfying_document_ids: list[uuid.UUID]
    note: str | None = None
    # Unsatisfied because a document that carries it cannot be read (VRT-112):
    # the client sends a clearer copy, not another document.
    unreadable: list[UnreadableEvidence] = []
    # There, but without what the process asks it to carry (VRT-118).
    lacks: ConditionKind | None = None

    @property
    def condition_kind(self) -> ConditionKind:
        if self.lacks is not None:
            return self.lacks
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
        present = [d for d in documents if d.document_type == item.document_type and d.status != "failed"]
        if len(present) < item.min_count:
            return ChecklistOutcome(item=item, applicable=True, satisfied=False, satisfying_document_ids=[d.document_id for d in present], note=note)
        return _attested(item, present, note)

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


def _attested(item: ChecklistItem, present: list[CaseDocument], note: str | None) -> ChecklistOutcome:
    """The documents are there; are they signed and sealed as the process asks (VRT-118)?
    A signature nobody could check is a person's to look at, not the client's to redo."""
    ok = present
    lacks: ConditionKind | None = None
    if item.must_be_sealed:
        ok = [d for d in ok if d.attestations is not None and d.attestations.sealed]
        lacks = "unsealed_document" if len(ok) < item.min_count else None
    if lacks is None and item.must_be_signed:
        signed = [d for d in ok if d.attestations is not None and d.attestations.signed]
        if len(signed) < item.min_count:
            unchecked = any(d.attestations is None or d.attestations.signed is None for d in ok)
            lacks = "unchecked_signature" if unchecked else "unsigned_document"
        ok = signed
    if lacks is not None:
        return ChecklistOutcome(item=item, applicable=True, satisfied=False, satisfying_document_ids=[], note=note, lacks=lacks)
    return ChecklistOutcome(item=item, applicable=True, satisfied=True, satisfying_document_ids=[d.document_id for d in ok], note=note)
