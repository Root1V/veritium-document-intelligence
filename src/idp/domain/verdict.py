"""The case verdict (VRT-27): what the calling process should do next, and
why. Pure — computed from the case's current state:

- a required document or evidence still missing (open condition) → the
  client must act: ``return_to_client``;
- a field awaiting human review, or a document that could not be processed
  → ``human_review``;
- a failed rule whose profile binding is ``blocking`` → that binding's
  ``on_fail``;
- otherwise → ``continue``.

Precedence when several apply: return_to_client > human_review > continue.
Every reason is reported, not only the one that decided.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from idp.domain.process_profile import ProcessProfileDefinition

Decision = Literal["continue", "human_review", "return_to_client"]
ReasonKind = Literal["missing_document", "missing_evidence", "rule", "pending_review", "failed_document"]

_PRECEDENCE: dict[str, int] = {"continue": 0, "human_review": 1, "return_to_client": 2}


class VerdictReason(BaseModel):
    kind: ReasonKind
    decision: Decision
    message: str
    ref: dict[str, Any]


class CaseVerdict(BaseModel):
    decision: Decision
    reasons: list[VerdictReason]


@dataclass(frozen=True)
class OpenCondition:
    key: str
    label: str
    kind: Literal["missing_document", "missing_evidence"]


@dataclass(frozen=True)
class FindingInput:
    rule_id: str
    message: str
    document_id: uuid.UUID | None


@dataclass
class VerdictInputs:
    open_conditions: list[OpenCondition] = field(default_factory=list)
    findings: list[FindingInput] = field(default_factory=list)
    pending_review_document_ids: set[uuid.UUID] = field(default_factory=set)
    failed_document_ids: set[uuid.UUID] = field(default_factory=set)


def decide(inputs: VerdictInputs, definition: ProcessProfileDefinition | None) -> CaseVerdict:
    reasons: list[VerdictReason] = []
    for c in inputs.open_conditions:
        reasons.append(VerdictReason(kind=c.kind, decision="return_to_client", message=f"Falta: {c.label}", ref={"condition_key": c.key}))
    for doc_id in sorted(inputs.failed_document_ids, key=str):
        reasons.append(
            VerdictReason(kind="failed_document", decision="human_review", message="Un documento no se pudo procesar.", ref={"document_id": str(doc_id)})
        )
    for doc_id in sorted(inputs.pending_review_document_ids, key=str):
        reasons.append(
            VerdictReason(
                kind="pending_review", decision="human_review", message="Hay campos pendientes de revisión humana.", ref={"document_id": str(doc_id)}
            )
        )
    if definition is not None:
        for f in inputs.findings:
            binding = definition.binding_for(f.rule_id)
            if binding is not None and binding.blocking:
                # A finding may say several things, one per line (e.g. each attribute in conflict): one reason each.
                reasons.extend(
                    VerdictReason(
                        kind="rule",
                        decision=binding.on_fail,
                        message=line,
                        ref={"rule_id": f.rule_id, "document_id": str(f.document_id) if f.document_id else None},
                    )
                    for line in f.message.splitlines()
                    if line.strip()
                )
    decision: Decision = "continue"
    for r in reasons:
        if _PRECEDENCE[r.decision] > _PRECEDENCE[decision]:
            decision = r.decision
    return CaseVerdict(decision=decision, reasons=reasons)
