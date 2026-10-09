"""Category (e): verification against a system the platform doesn't own, via
``ExternalSystemPort``. Phase 0 injects a stub/test-double (see
``validation.ports.StubExternalSystemPort``); a real MCP-backed adapter is a
Fase 1+ milestone (roadmap item 2) — the port is already defined and
inject-able, so that milestone only swaps the adapter."""

from __future__ import annotations

from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.context import ValidationContext


class InsurancePolicyVerifiedExternally(ValidationRule):
    rule_id = "external_system.insurance_policy_verified"
    reads = frozenset({"policy_number"})
    category = RuleCategory.EXTERNAL_SYSTEM

    def applies_when(self, context: ValidationContext) -> bool:
        return context.current_document.document_type == "insurance_disclosure" and bool(
            context.current_document.fields.get("policy_number")
        )

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        policy_number = context.current_document.fields["policy_number"]
        response = await context.external_system.verify(system="insurer", query={"policy_number": policy_number})
        passed = bool(response.get("verified"))
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else Severity.WARNING,
            field_path="policy_number",
            message="Poliza verificada contra el sistema externo." if passed else "No se pudo verificar la poliza contra el sistema externo.",
            actual=policy_number,
            confidence=1.0 if passed else 0.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation=f"Respuesta de ExternalSystemPort (stub en Fase 0; adaptador MCP real en Fase 1+): {response!r}.",
        )
