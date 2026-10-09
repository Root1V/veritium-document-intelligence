"""Category (a): externally-supplied request-input data (JSON/form) contrasted
against data extracted from the request's documents. Pure Python, always
deterministic — the payload's own fields are exact expectations, not fuzzy
identity claims."""

from __future__ import annotations

from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.context import ValidationContext


class ExpectedEmployeeCodeMatches(ValidationRule):
    rule_id = "request_input.expected_employee_code_matches"
    reads = frozenset({"employee_code"})
    category = RuleCategory.REQUEST_INPUT

    def applies_when(self, context: ValidationContext) -> bool:
        return context.request_payload.get("expected_employee_code") is not None

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        expected = context.request_payload.get("expected_employee_code")
        actual = context.current_document.fields.get("employee_code")
        passed = expected == actual
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else Severity.ERROR,
            field_path="employee_code",
            message="employee_code coincide con el payload de la solicitud." if passed else "employee_code no coincide con el payload de la solicitud.",
            expected=expected,
            actual=actual,
            confidence=1.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation=f"Comparacion exacta: esperado={expected!r} (request_input_payload) vs extraido={actual!r} (documento).",
        )
