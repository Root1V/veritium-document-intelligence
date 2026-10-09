"""Category (b): cross-document validation within the same request/batch.
Two rules: exact duplicate-identifier detection (deterministic), and a
fuzzy_deterministic identity check between a payslip's employee_name and an
insurance disclosure's insured_name — the concrete case that motivated
``validation/entity_matching.py``."""

from __future__ import annotations

import asyncio

from idp.config import Settings
from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.context import ValidationContext
from idp.validation.entity_matching import EntityKind, escalate_to_llm_judge, match_entities


def _document_identifier(fields: dict) -> str | None:
    return fields.get("employee_code") or fields.get("policy_number")


def _full_name(fields: dict, *, first_key: str, paternal_key: str | None = None, maternal_key: str | None = None) -> str | None:
    """Peruvian-convention 'APELLIDOS, NOMBRE' assembled from separately
    extracted name-part fields (see insurance_disclosure.py's schema
    comment for why the parts stay split rather than being extracted as a
    single pre-concatenated field)."""
    first = fields.get(first_key)
    if not first:
        return None
    surnames = " ".join(p for p in (fields.get(paternal_key) if paternal_key else None, fields.get(maternal_key) if maternal_key else None) if p)
    return f"{surnames}, {first}" if surnames else first


class DuplicateDocumentIdentifier(ValidationRule):
    rule_id = "batch.duplicate_identifier"
    reads = frozenset({"employee_code", "policy_number"})
    category = RuleCategory.CROSS_DOCUMENT

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        current_id = _document_identifier(context.current_document.fields)
        duplicates = [
            sib
            for sib in context.sibling_documents
            if current_id is not None
            and sib.document_type == context.current_document.document_type
            and _document_identifier(sib.fields) == current_id
        ]
        passed = not duplicates
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else Severity.WARNING,
            message="Sin duplicados detectados en el batch." if passed else f"Identificador {current_id!r} duplicado en {len(duplicates)} documento(s) del mismo tipo en la solicitud.",
            actual=current_id,
            confidence=1.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation="Comparacion exacta de identificador (employee_code/policy_number) entre documentos del mismo tipo en la solicitud.",
        )


class EmployeeNameCrossDocumentMatch(ValidationRule):
    """The 'Victor Emeric Espiritu Santiago' vs 'Victor E. Espiritu Santiago'
    case: same person, different valid formats across a payslip and an
    insurance disclosure in the same request."""

    rule_id = "batch.employee_name_matches_insured_name"
    reads = frozenset({"employee_name", "insured_first_name", "insured_paternal_surname", "insured_maternal_surname"})
    category = RuleCategory.CROSS_DOCUMENT

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def applies_when(self, context: ValidationContext) -> bool:
        return context.current_document.document_type == "payslip" and any(
            sib.document_type == "insurance_disclosure" for sib in context.sibling_documents
        )

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        employee_name = context.current_document.fields.get("employee_name")
        sibling = next(sib for sib in context.sibling_documents if sib.document_type == "insurance_disclosure")
        insured_name = _full_name(
            sibling.fields,
            first_key="insured_first_name",
            paternal_key="insured_paternal_surname",
            maternal_key="insured_maternal_surname",
        )

        if not employee_name or not insured_name:
            return ValidationResult(
                rule_id=self.rule_id,
                category=self.category,
                passed=True,
                message="Datos insuficientes para comparar nombres; regla omitida.",
                confidence=1.0,
                confidence_method=ConfidenceMethod.DETERMINISTIC,
                explanation="employee_name o insured_name ausente en la extraccion.",
            )

        outcome = match_entities(
            EntityKind.PERSON,
            employee_name,
            insured_name,
            high_threshold=self._settings.entity_match_high_threshold,
            low_threshold=self._settings.entity_match_low_threshold,
        )

        if outcome.band == "ambiguous":
            verdict = await asyncio.to_thread(
                escalate_to_llm_judge,
                self._settings,
                kind=EntityKind.PERSON,
                value_a=employee_name,
                value_b=insured_name,
                outcome=outcome,
            )
            passed = verdict.is_match
            method = ConfidenceMethod.LLM_JUDGE
            explanation = (
                f"Comparacion de identidad (persona): {employee_name!r} (boleta, employee_name) vs "
                f"{insured_name!r} (seguro, insured_name). Score algoritmico ({outcome.metric})={outcome.score:.2f} "
                f"en banda ambigua -> escalado a LLM-juez. Veredicto: {verdict.is_match} ({verdict.reasoning})."
            )
        else:
            passed = outcome.band == "match"
            method = ConfidenceMethod.FUZZY_DETERMINISTIC
            explanation = (
                f"Comparacion de identidad (persona): {employee_name!r} (boleta, employee_name) vs "
                f"{insured_name!r} (seguro, insured_name). Normalizado: {outcome.normalized_a!r} vs "
                f"{outcome.normalized_b!r}. Metrica: {outcome.metric}={outcome.score:.2f} -> "
                f"{'MATCH' if passed else 'NO MATCH'} (fuzzy_deterministic)."
            )

        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else Severity.WARNING,
            field_path="employee_name",
            message="Nombre coincide entre boleta y seguro (misma persona)." if passed else "Nombre no coincide entre boleta y seguro.",
            expected=insured_name,
            actual=employee_name,
            confidence=outcome.score,
            confidence_method=method,
            explanation=explanation,
        )
