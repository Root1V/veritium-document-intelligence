"""Catalog-driven rules. Category (b): the generic cross-document consistency check
over the semantic view (VRT-23). Replaces the need for one hand-written
pairwise rule per (document type, document type, field) — any two documents
that map a field to the same role and attribute are compared. The
hand-written cross-document rules in batch_rules.py stay active until F2
(strangler); this rule never escalates to an LLM judge."""

from __future__ import annotations

from idp.domain.semantic import SemanticAttribute, SemanticCatalog
from idp.domain.semantic_resolution import EvidenceSource, describe_conflict
from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.cel import CelEvaluationError, compile_expression, evaluate
from idp.validation.context import ValidationContext


class SemanticAttributeConsistency(ValidationRule):
    rule_id = "semantic.attribute_consistency"
    reads = frozenset({"@*"})
    category = RuleCategory.CROSS_DOCUMENT

    def applies_when(self, context: ValidationContext) -> bool:
        return context.semantic_view is not None

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        assert context.semantic_view is not None
        conflicts = context.semantic_view.conflicts_involving(context.current_document.document_id)
        if not conflicts:
            return ValidationResult(
                rule_id=self.rule_id,
                category=self.category,
                passed=True,
                message="Sin inconsistencias con los demás documentos del expediente.",
                confidence=1.0,
                confidence_method=ConfidenceMethod.FUZZY_DETERMINISTIC,
                explanation="Todos los atributos semánticos que este documento comparte con otros coinciden.",
            )
        details = [describe_conflict(c) for c in conflicts]
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=False,
            severity=Severity.WARNING,
            field_path=",".join(f"{c.role}.{c.attribute}" for c in conflicts),
            message=f"{len(conflicts)} atributo(s) no coinciden con otros documentos del expediente: " + "; ".join(details),
            expected={f"{c.role}.{c.attribute}": c.distinct_values for c in conflicts},
            actual=None,
            confidence=1.0,
            confidence_method=ConfidenceMethod.FUZZY_DETERMINISTIC,
            explanation=(
                "Resolución sobre el catálogo semántico: los documentos que mapean un campo al mismo rol y atributo "
                "se comparan según el tipo de comparación del atributo (identificador exacto, nombre difuso, número con tolerancia, fecha normalizada)."
            ),
        )


class SemanticAttributeFormat(ValidationRule):
    """Category (a), catalog-driven (VRT-35): an attribute's intrinsic
    format — its ``format_cel`` over ``value`` — checked on every value any
    document contributes to that attribute, whatever the document type. A
    DNI is 8 digits wherever it appears, so the check is written once, on
    ``persona.dni``, instead of once per document type that carries a DNI.
    One instance per attribute that declares a format, built from the
    catalog version the run resolves against."""

    category = RuleCategory.SELF

    def __init__(self, attribute: SemanticAttribute) -> None:
        self.rule_id = format_rule_id(attribute.key)
        self.reads = frozenset({f"@{attribute.key}"})
        self._attribute = attribute
        self._program = compile_expression(attribute.format_cel or "true")

    def _values(self, context: ValidationContext) -> list[EvidenceSource]:
        assert context.semantic_view is not None
        return [
            s
            for r in context.semantic_view.attributes
            if r.attribute == self._attribute.key
            for s in r.sources
            if s.document_id == context.current_document.document_id and s.value not in (None, "")
        ]

    def applies_when(self, context: ValidationContext) -> bool:
        return context.semantic_view is not None and bool(self._values(context))

    def _valid(self, value: object) -> bool:
        try:
            return bool(evaluate(self._program, {"value": str(value).strip()}))  # celpy answers BoolType, not True
        except CelEvaluationError:
            return False

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        sources = self._values(context)
        invalid = [s for s in sources if not self._valid(s.value)]
        name, key = self._attribute.name, self._attribute.key
        if not invalid:
            return ValidationResult(
                rule_id=self.rule_id,
                category=self.category,
                passed=True,
                message=f"{name}: formato válido.",
                confidence=1.0,
                confidence_method=ConfidenceMethod.DETERMINISTIC,
                explanation=f"{', '.join(s.field_path for s in sources)} cumple el formato de {key} ({self._attribute.format_cel}).",
            )
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=False,
            severity=Severity.ERROR,
            field_path=",".join(s.field_path for s in invalid),
            message=f"{name} sin formato válido: " + "; ".join(f"{s.field_path}={s.value!r}" for s in invalid),
            expected=self._attribute.definition,
            actual=[s.value for s in invalid],
            confidence=1.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation=f"El atributo {key} exige {self._attribute.format_cel} en cualquier documento (catálogo semántico).",
        )


def format_rule_id(attribute_key: str) -> str:
    return f"semantic.format.{attribute_key}"


def format_rules(catalog: SemanticCatalog) -> list[ValidationRule]:
    return [SemanticAttributeFormat(a) for a in catalog.attributes if a.format_cel]
