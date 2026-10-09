"""Shared value objects for the validation engine: ``ValidationResult`` (and
its convenience alias ``ValidationIssue`` for non-passing results),
``Severity``, ``RuleCategory``, and ``ConfidenceMethod``.

Not every validation is deterministic equality — see ``ConfidenceMethod``:
``fuzzy_deterministic`` is a distinct third mode (a reproducible similarity
score, not a model judgement) sitting between plain ``deterministic`` checks
and ``llm_judge``/``multi_signal`` ones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from idp.validation.context import ValidationContext


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RuleCategory(StrEnum):
    SELF = "self"  # intra-document arithmetic/format consistency (predates the user's 5-category feedback, still in scope)
    REQUEST_INPUT = "request_input"  # (a)
    CROSS_DOCUMENT = "cross_document"  # (b)
    CONDITIONAL = "conditional"  # (c)
    REFERENCE_DATA = "reference_data"  # (d)
    EXTERNAL_SYSTEM = "external_system"  # (e)


class ConfidenceMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    FUZZY_DETERMINISTIC = "fuzzy_deterministic"
    LLM_JUDGE = "llm_judge"
    MULTI_SIGNAL = "multi_signal"


class ValidationResult(BaseModel):
    """Value object produced by ``ValidationRule.evaluate`` — never mutated
    after creation. A passing result (``severity=None``) is still recorded
    for audit/explainability; only non-passing ones become persisted
    ``ValidationIssue`` rows (see ``persistence.models.ValidationIssue``)."""

    rule_id: str
    category: RuleCategory
    passed: bool
    severity: Severity | None = None
    field_path: str | None = None
    message: str
    expected: Any = None
    actual: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_method: ConfidenceMethod
    explanation: str


class ValidationRule(ABC):
    """Strategy interface unifying all 5 validation categories. Concrete
    rules live in ``validation/rules/*.py``, one module per category (plus
    ``conditional.py``, which is transversal — it wraps another rule with an
    ``applies_when`` gate rather than being its own category of check)."""

    rule_id: str
    category: RuleCategory
    depends_on: list[str] = []
    # What the rule reads (VRT-40), so a reprocess re-evaluates only the
    # rules a changed field reaches: field names (any document type) and
    # semantic attributes as "@<entity>.<name>"; "@*" is any attribute.
    # None means unknown — always re-evaluated.
    reads: frozenset[str] | None = None

    def applies_when(self, context: "ValidationContext") -> bool:
        """Activation gate for conditional rules (category c chaining onto
        any other category). Defaults to always-applies."""
        return True

    @abstractmethod
    async def evaluate(self, context: "ValidationContext") -> ValidationResult: ...
