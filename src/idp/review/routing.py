"""Per-field (not per-document) confidence-based review routing. Walks every
``Extracted[T]`` leaf in an extraction schema and flags it when its
confidence is below threshold, or a validation rule touched that field with
a non-passing result of severity >= warning. With an active calibration
(VRT-43) the confidence compared is the calibrated one: the accuracy
observed for that field at that raw confidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from idp.domain.envelope import Extracted
from idp.validation.base import Severity, ValidationResult


class ReviewCandidate(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    field_path: str
    value: Any
    confidence: float
    reason: str  # "low_confidence" | "validation_issue"


def _walk(instance: object, prefix: str, out: list[tuple[str, Extracted]]) -> None:
    if isinstance(instance, Extracted):
        out.append((prefix, instance))
    elif isinstance(instance, BaseModel):
        for name in type(instance).model_fields:
            child_prefix = f"{prefix}.{name}" if prefix else name
            _walk(getattr(instance, name), child_prefix, out)
    elif isinstance(instance, list):
        for i, item in enumerate(instance):
            _walk(item, f"{prefix}[{i}]", out)


def find_review_candidates(
    schema_instance: BaseModel,
    validation_results: list[ValidationResult],
    *,
    confidence_threshold: float,
    calibrate: Callable[[str, float], float] | None = None,
) -> list[ReviewCandidate]:
    leaves: list[tuple[str, Extracted]] = []
    _walk(schema_instance, "", leaves)

    issue_fields = {
        r.field_path
        for r in validation_results
        if not r.passed and r.severity in (Severity.WARNING, Severity.ERROR) and r.field_path
    }

    candidates: list[ReviewCandidate] = []
    for path, extracted in leaves:
        confidence = calibrate(path, extracted.confidence) if calibrate is not None else extracted.confidence
        if confidence < confidence_threshold:
            candidates.append(
                ReviewCandidate(field_path=path, value=extracted.value, confidence=extracted.confidence, reason="low_confidence")
            )
        elif path in issue_fields:
            candidates.append(
                ReviewCandidate(field_path=path, value=extracted.value, confidence=extracted.confidence, reason="validation_issue")
            )
    return candidates
