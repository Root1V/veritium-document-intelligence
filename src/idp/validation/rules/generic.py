"""A single generic ValidationRule that executes a DB-stored CEL
condition — the data-driven analog of self_rules.py::DniFormatValid being
one Python class parametrized many times, except parametrized by a
persistence.models.ValidationRuleDefinition row instead of constructor
args written in code. Only kind="cel" rows become instances of this class
(see pipeline/orchestrator.py::build_default_rules); kind="toggle" rows
never do — they only gate whether an existing hardcoded rule instance is
included in the list at all."""

from __future__ import annotations

from typing import Any

from idp.persistence.models import ValidationRuleDefinition
from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.cel import CelEvaluationError, compile_expression, evaluate
from idp.validation.context import ValidationContext


class DataDrivenRule(ValidationRule):
    def __init__(self, row: ValidationRuleDefinition) -> None:
        self.rule_id = row.rule_id
        self.category = RuleCategory(row.category)
        self._row = row
        # Compiled once at construction (not per evaluate() call) — rows
        # are loaded fresh from the DB every batch run by
        # build_default_rules, so this doesn't go stale across a rule
        # edit; it just avoids recompiling the same expression once per
        # document in a multi-document batch.
        self._condition_program = compile_expression(row.condition_cel)
        self._applies_when_program = compile_expression(row.applies_when_cel) if row.applies_when_cel else None

    @property
    def definition_version(self) -> str:
        """Identifies the exact rule definition that ran (for provenance):
        an active CEL rule is immutable, so its last update stamps it."""
        updated = self._row.updated_at or self._row.created_at
        return updated.isoformat() if updated else "unknown"

    def applies_when(self, context: ValidationContext) -> bool:
        # applies_when() is synchronous in the ABC (validation/base.py) —
        # that's why this gate never has access to reference_data.*
        # (which needs await), only doc./request. Existence-in-reference-
        # data checks always live in condition_cel, never applies_when_cel.
        if self._row.document_type is not None and context.current_document.document_type != self._row.document_type:
            return False
        if self._applies_when_program is None:
            return True
        try:
            result = evaluate(
                self._applies_when_program,
                _cel_env(context),
            )
        except CelEvaluationError:
            return False  # a gate that can't evaluate fails closed
        return bool(result)

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        env: dict[str, Any] = _cel_env(context)

        if self.category == RuleCategory.REFERENCE_DATA:
            # The only I/O a data-driven rule can trigger: the same exact
            # lookup EmployeeCodeExistsInReferenceData already uses (same
            # port, same method) — resolved in Python BEFORE evaluating
            # CEL, never invoked from inside the expression itself. CEL
            # only ever reads the boolean result; there's no custom CEL
            # function and no new query surface.
            code_field = self._row.field_path or "employee_code"
            code = context.current_document.fields.get(code_field)
            exists = False
            if code:
                record = await context.reference_data.find_employee_by_code(code)
                exists = record is not None
            env["reference_data"] = {"employee_code_exists": exists}

        try:
            passed = bool(evaluate(self._condition_program, env))
        except CelEvaluationError as exc:
            return ValidationResult(
                rule_id=self.rule_id,
                category=self.category,
                passed=True,
                message="No se pudo evaluar la condicion (campo ausente o tipo incompatible); regla omitida.",
                confidence=1.0,
                confidence_method=ConfidenceMethod.DETERMINISTIC,
                explanation=f"CEL condition_cel={self._row.condition_cel!r} fallo en tiempo de evaluacion: {exc}.",
            )

        severity = Severity(self._row.severity) if self._row.severity else Severity.WARNING
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else severity,
            field_path=self._row.field_path,
            message=(self._row.message_pass or "Condicion cumplida.") if passed else (self._row.message_fail or "Condicion no cumplida."),
            confidence=1.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation=f"Regla data-driven (CEL): {self._row.condition_cel!r} -> {passed}.",
        )


def _cel_env(context: ValidationContext) -> dict[str, Any]:
    """Variables visible to a rule's CEL: `doc` (this document's fields),
    `request` (the caller's process data) and `case` (the case's semantic
    view, e.g. `case.titular.persona.dni`; empty when there is none)."""
    return {
        "doc": context.current_document.fields,
        "request": context.request_payload.data,
        "case": context.semantic_view.as_cel() if context.semantic_view is not None else {},
    }
