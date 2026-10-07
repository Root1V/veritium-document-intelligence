"""Category (b), catalog-driven: the generic cross-document consistency check
over the semantic view (VRT-23). Replaces the need for one hand-written
pairwise rule per (document type, document type, field) — any two documents
that map a field to the same role and attribute are compared. The
hand-written cross-document rules in batch_rules.py stay active until F2
(strangler); this rule never escalates to an LLM judge."""

from __future__ import annotations

from idp.domain.semantic_resolution import describe_conflict
from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.context import ValidationContext


class SemanticAttributeConsistency(ValidationRule):
    rule_id = "semantic.attribute_consistency"
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
