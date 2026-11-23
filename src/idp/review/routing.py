"""Per-field (not per-document) confidence-based review routing. Walks every
``Extracted[T]`` leaf in an extraction schema and flags it when its
confidence is below threshold, or a validation rule touched that field with
a non-passing result of severity >= warning, or the agent said it cannot be read
(VRT-112), or its value is nowhere in the text read from the document (VRT-113), or the OCR
read its region with little certainty (VRT-115). With an active calibration
(VRT-43) the confidence compared is the calibrated one: the accuracy
observed for that field at that raw confidence."""

from __future__ import annotations

import typing
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from idp.domain.envelope import Extracted
from idp.validation.base import Severity, ValidationResult


class ReviewCandidate(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    field_path: str
    value: Any
    confidence: float
    reason: str  # "low_confidence" | "validation_issue" | "unreadable" | "not_in_text" | "low_read"


# Below it the OCR misreads: measured 2026-11-23, 94 % of the lines read under
# 0.9 on degraded scans were wrong, and 1 of 1,088 values of the clean bench
# falls under it (under 0.95 it would be 73, with no more errors among them).
READ_CONFIDENCE_FLOOR = 0.9


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


def _not_in_text(path: str, extracted: Extracted) -> bool:
    """A value grounding could not find in any region of the read text: the
    agent saw it only in the image, or computed or inferred it. Fields the
    model infers by design — a choice among options (a concept's kind) and
    the summary — are not read from a region. Measured on the bench: no
    value of a clean document is ever left unlocated (2026-11-22)."""
    if extracted.page is not None or extracted.value in (None, "") or path.rsplit(".", 1)[-1] == "summary":
        return False
    return typing.get_origin(type(extracted).model_fields["value"].annotation) is not Literal


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

    unreadable = {u.field for u in getattr(schema_instance, "unreadable_fields", ())}
    # Catalog types (they carry unreadable_fields) are the ones measured for the not-in-text signal.
    catalog_type = hasattr(schema_instance, "unreadable_fields")

    candidates: list[ReviewCandidate] = []
    for path, extracted in leaves:
        confidence = calibrate(path, extracted.confidence) if calibrate is not None else extracted.confidence
        if path in unreadable:
            candidates.append(ReviewCandidate(field_path=path, value=extracted.value, confidence=extracted.confidence, reason="unreadable"))
        elif catalog_type and _not_in_text(path, extracted):
            candidates.append(ReviewCandidate(field_path=path, value=extracted.value, confidence=extracted.confidence, reason="not_in_text"))
        elif extracted.read_confidence is not None and extracted.read_confidence < READ_CONFIDENCE_FLOOR:
            # The confidence shown is the reading's: the agent's (often 1.0) would contradict the reason.
            candidates.append(ReviewCandidate(field_path=path, value=extracted.value, confidence=extracted.read_confidence, reason="low_read"))
        elif confidence < confidence_threshold:
            candidates.append(
                ReviewCandidate(field_path=path, value=extracted.value, confidence=extracted.confidence, reason="low_confidence")
            )
        elif path in issue_fields:
            candidates.append(
                ReviewCandidate(field_path=path, value=extracted.value, confidence=extracted.confidence, reason="validation_issue")
            )
    return candidates
