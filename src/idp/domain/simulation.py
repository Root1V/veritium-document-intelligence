"""What-if simulation and shadow mode (VRT-44), the pure part: what changes
between a case's real decision and the candidate's, and the summary a
person reads — how many cases would change, and from what to what."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from pydantic import BaseModel


class Difference(BaseModel):
    added_reasons: list[str]
    removed_reasons: list[str]


def _identity(reason: dict[str, Any]) -> str:
    """A reason is what it is about — the requirement, or the rule and the
    document — not its wording, which may list the same facts in another
    order."""
    return json.dumps([reason.get("kind"), reason.get("ref")], sort_keys=True)


def _messages(reasons: list[dict[str, Any]], keep: set[str]) -> list[str]:
    seen: list[str] = []
    for r in reasons:
        if _identity(r) in keep and r.get("message") and r["message"] not in seen:
            seen.append(r["message"])  # a reason given once per document reads once
    return seen


def difference(actual_reasons: list[dict[str, Any]] | None, simulated_reasons: list[dict[str, Any]] | None) -> Difference:
    actual, simulated = actual_reasons or [], simulated_reasons or []
    before, after = {_identity(r) for r in actual}, {_identity(r) for r in simulated}
    return Difference(added_reasons=_messages(simulated, after - before), removed_reasons=_messages(actual, before - after))


class Outcome(BaseModel):
    actual_verdict: str | None
    simulated_verdict: str | None
    failed: bool = False


class Transition(BaseModel):
    before: str | None
    after: str | None
    count: int


class SimulationSummary(BaseModel):
    cases: int
    failed: int
    changed: int
    agreement: float | None  # share of decided cases whose decision does not change
    before: dict[str, int]  # decision -> cases, as it really was
    after: dict[str, int]  # decision -> cases, with the candidate
    transitions: list[Transition]  # only the changes, most frequent first


def summarize(outcomes: list[Outcome]) -> SimulationSummary:
    decided = [o for o in outcomes if not o.failed]
    changes = Counter((o.actual_verdict, o.simulated_verdict) for o in decided if o.actual_verdict != o.simulated_verdict)
    return SimulationSummary(
        cases=len(outcomes),
        failed=len(outcomes) - len(decided),
        changed=sum(changes.values()),
        agreement=round(1 - sum(changes.values()) / len(decided), 4) if decided else None,
        before=dict(Counter(o.actual_verdict or "sin_veredicto" for o in decided)),
        after=dict(Counter(o.simulated_verdict or "sin_veredicto" for o in decided)),
        transitions=[Transition(before=b, after=a, count=n) for (b, a), n in changes.most_common()],
    )
