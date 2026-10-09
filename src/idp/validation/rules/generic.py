"""A single generic ValidationRule that executes a DB-stored CEL
condition — one Python class parametrized many times, by a
persistence.models.ValidationRuleDefinition row instead of constructor
args written in code. Only kind="cel" rows become instances of this class
(see pipeline/orchestrator.py::build_default_rules); kind="toggle" rows
never do — they only gate whether an existing hardcoded rule instance is
included in the list at all."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from idp.domain.rule_draft import RuleTestCase
from idp.persistence.models import ValidationRuleDefinition
from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.cel import CelEvaluationError, compile_expression, evaluate
from idp.validation.context import ValidationContext


_DOC_FIELD = re.compile(r"\bdoc\.(\w+)")
_CASE_ATTRIBUTE = re.compile(r"\bcase\.\w+\.(\w+)\.(\w+)")


def cel_reads(expressions: list[str], *, attribute: str | None) -> frozenset[str] | None:
    """What a CEL rule reads (ValidationRule.reads): ``doc.<field>`` and
    ``case.<role>.<entity>.<name>`` references, plus the rule's own
    attribute. None (unknown) when ``doc`` or ``case`` is used some other
    way, e.g. ``doc["x"]`` or a whole ``case.titular``."""
    reads: set[str] = {f"@{attribute}"} if attribute else set()
    for expression in expressions:
        fields = _DOC_FIELD.findall(expression)
        attributes = _CASE_ATTRIBUTE.findall(expression)
        if len(fields) != len(re.findall(r"\bdoc\b", expression)) or len(attributes) != len(re.findall(r"\bcase\b", expression)):
            return None
        reads.update(fields)
        reads.update(f"@{entity}.{name}" for entity, name in attributes)
    return frozenset(reads)


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
        self.reads = cel_reads([e for e in (row.condition_cel, row.applies_when_cel) if e], attribute=row.attribute)

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
        if self._row.attribute is not None and not self._attribute_values(context):
            return False  # a rule over an attribute runs where a document contributes it (VRT-36)
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

        field_path = self._row.field_path
        try:
            if self._row.attribute is None:
                passed = bool(evaluate(self._condition_program, env))
            else:
                failing = [path for path, value in self._attribute_values(context) if not bool(evaluate(self._condition_program, env | {"value": value}))]
                passed, field_path = not failing, ",".join(failing) or None
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
            field_path=field_path,
            message=(self._row.message_pass or "Condicion cumplida.") if passed else (self._row.message_fail or "Condicion no cumplida."),
            confidence=1.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation=f"Regla data-driven (CEL): {self._row.condition_cel!r} -> {passed}.",
        )


    def _attribute_values(self, context: ValidationContext) -> list[tuple[str, Any]]:
        """(field path, value) of every value this document contributes to
        the rule's attribute, in any role."""
        if context.semantic_view is None:
            return []
        return [
            (s.field_path, s.value)
            for r in context.semantic_view.attributes
            if r.attribute == self._row.attribute
            for s in r.sources
            if s.document_id == context.current_document.document_id and s.value not in (None, "")
        ]


def _cel_env(context: ValidationContext) -> dict[str, Any]:
    """Variables visible to a rule's CEL: `doc` (this document's fields),
    `request` (the caller's process data) and `case` (the case's semantic
    view, e.g. `case.titular.persona.dni`; empty when there is none)."""
    return {
        "doc": context.current_document.fields,
        "request": context.request_payload.data,
        "case": context.semantic_view.as_cel() if context.semantic_view is not None else {},
    }


class TestCaseResult(BaseModel):
    name: str
    expect: str
    got: str  # pass | fail | error
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.got == self.expect


def _as(kind: str | None, value: Any) -> Any:
    if kind in ("float", "number") and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if kind in ("int", "integer") and isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def run_test_cases(
    condition_cel: str,
    applies_when_cel: str | None,
    cases: list[RuleTestCase],
    *,
    value_type: str | None = None,
    field_types: dict[str, str] | None = None,
) -> list[TestCaseResult]:
    """What each test case gives against the rule's CEL — the same
    variables the rule sees at run time (VRT-36). A case where the rule
    does not apply (applies_when false) counts as 'pass': it raises no finding.

    CEL does not compare int with double, and extraction delivers each
    value with its declared type; so a case's ``value`` and ``doc`` numbers
    take the type the attribute (``value_type``) or the document type's
    fields (``field_types``) declare, as they would at run time."""
    condition = compile_expression(condition_cel)
    gate = compile_expression(applies_when_cel) if applies_when_cel else None
    results = []
    for case in cases:
        env = case.input.model_dump()
        env["value"] = _as(value_type, env["value"])
        env["doc"] = {k: _as((field_types or {}).get(k), v) for k, v in env["doc"].items()}
        try:
            applies = bool(evaluate(gate, env)) if gate is not None else True
            got = "pass" if not applies or bool(evaluate(condition, env)) else "fail"
            results.append(TestCaseResult(name=case.name, expect=case.expect, got=got))
        except CelEvaluationError as exc:
            results.append(TestCaseResult(name=case.name, expect=case.expect, got="error", detail=str(exc)))
    return results

