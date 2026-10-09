"""Category (d): existence-in-database checks against internal reference
data (``ReferenceDataPort``, Postgres-backed in Phase 0 via
``persistence.repositories.ReferenceDataRepository``). Exact lookup by code
is deterministic; lookup by name alone uses the same fuzzy_deterministic
path as category (b) via ``entity_matching.py``."""

from __future__ import annotations

import asyncio

from idp.config import Settings
from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.context import ValidationContext
from idp.validation.entity_matching import EntityKind, escalate_to_llm_judge, match_entities


class EmployeeCodeExistsInReferenceData(ValidationRule):
    rule_id = "reference_data.employee_code_exists"
    reads = frozenset({"employee_code"})
    category = RuleCategory.REFERENCE_DATA

    def applies_when(self, context: ValidationContext) -> bool:
        return bool(context.current_document.fields.get("employee_code"))

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        employee_code = context.current_document.fields["employee_code"]
        record = await context.reference_data.find_employee_by_code(employee_code)
        passed = record is not None
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else Severity.ERROR,
            field_path="employee_code",
            message="El código de empleado existe en el maestro de empleados." if passed else "El código de empleado no existe en el maestro de empleados.",
            actual=employee_code,
            confidence=1.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation=f"Lookup exacto de employee_code={employee_code!r} contra reference_employees.",
        )


class EmployeeNameExistsInReferenceData(ValidationRule):
    """Fuzzy lookup path: used when the document only carries a name, not a
    code — finds the best-matching reference employee and applies the same
    fuzzy/escalation bands as category (b)."""

    rule_id = "reference_data.employee_name_matches_reference"
    reads = frozenset({"employee_code", "employee_name"})
    category = RuleCategory.REFERENCE_DATA

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def applies_when(self, context: ValidationContext) -> bool:
        return not context.current_document.fields.get("employee_code") and bool(
            context.current_document.fields.get("employee_name")
        )

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        employee_name = context.current_document.fields["employee_name"]
        candidates = await context.reference_data.list_active_employee_names()

        if not candidates:
            return ValidationResult(
                rule_id=self.rule_id,
                category=self.category,
                passed=False,
                severity=Severity.WARNING,
                field_path="employee_name",
                message="No hay empleados de referencia con los que comparar.",
                actual=employee_name,
                confidence=1.0,
                confidence_method=ConfidenceMethod.DETERMINISTIC,
                explanation="La tabla de referencia de empleados esta vacia.",
            )

        best_code, best_outcome, best_name = max(
            (
                (code, match_entities(
                    EntityKind.PERSON, employee_name, full_name,
                    high_threshold=self._settings.entity_match_high_threshold,
                    low_threshold=self._settings.entity_match_low_threshold,
                ), full_name)
                for code, full_name in candidates
            ),
            key=lambda item: item[1].score,
        )

        if best_outcome.band == "ambiguous":
            verdict = await asyncio.to_thread(
                escalate_to_llm_judge,
                self._settings,
                kind=EntityKind.PERSON,
                value_a=employee_name,
                value_b=best_name,
                outcome=best_outcome,
            )
            passed = verdict.is_match
            method = ConfidenceMethod.LLM_JUDGE
            explanation = (
                f"Mejor candidato de referencia: {best_name!r} (codigo {best_code}). "
                f"Score={best_outcome.score:.2f} en banda ambigua -> LLM-juez: {verdict.is_match} ({verdict.reasoning})."
            )
        else:
            passed = best_outcome.band == "match"
            method = ConfidenceMethod.FUZZY_DETERMINISTIC
            explanation = (
                f"Mejor candidato de referencia: {best_name!r} (codigo {best_code}). "
                f"Normalizado: {best_outcome.normalized_a!r} vs {best_outcome.normalized_b!r}. "
                f"Metrica {best_outcome.metric}={best_outcome.score:.2f} -> {'MATCH' if passed else 'NO MATCH'}."
            )

        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else Severity.WARNING,
            field_path="employee_name",
            message="Nombre coincide con un empleado de referencia." if passed else "Nombre no coincide con ningun empleado de referencia.",
            expected=best_name,
            actual=employee_name,
            confidence=best_outcome.score,
            confidence_method=method,
            explanation=explanation,
        )
