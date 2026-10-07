"""Seed process profiles, published as version 1 when the profiles table is
empty (see ``ProcessProfileRepository.ensure_seed``).

- ``ad-hoc``: the built-in profile behind the legacy ``/batches`` API — no
  checklist, every active rule with its default severity (v0.3.0 behaviour).
- ``convenios``: a payroll-agreement loan ("préstamo por convenio") as a
  worked example of every profile feature: requirements by document type,
  one by semantic attribute (income evidence, satisfiable by a payslip or a
  debt capacity calculation), one conditional on the process data, and rule
  bindings with their own severity.
"""

from __future__ import annotations

from idp.domain.process_profile import ChecklistItem, ProcessProfileDefinition, RuleBinding, Thresholds
from idp.validation.base import Severity

SEED_CATALOG_VERSION = 1

AD_HOC_KEY = "ad-hoc"


def ad_hoc_definition() -> ProcessProfileDefinition:
    return ProcessProfileDefinition(semantic_catalog_version=SEED_CATALOG_VERSION, include_all_rules=True)


def convenios_definition() -> ProcessProfileDefinition:
    return ProcessProfileDefinition(
        semantic_catalog_version=SEED_CATALOG_VERSION,
        checklist=[
            ChecklistItem(key="solicitud", label="Solicitud de préstamo por convenio", document_type="loan_application"),
            ChecklistItem(key="autorizacion_descuento", label="Carta de autorización de descuento por planilla", document_type="authorization_letter"),
            ChecklistItem(key="seguro_desgravamen", label="Declaración personal de seguro de desgravamen", document_type="insurance_disclosure"),
            ChecklistItem(
                key="evidencia_ingreso",
                label="Evidencia del ingreso neto mensual del titular (boleta de pago o cálculo de capacidad)",
                requires_attributes=["ingreso.neto_mensual"],
                role="titular",
            ),
            ChecklistItem(
                key="carne_extranjeria",
                label="Carné de extranjería (si el titular no es peruano)",
                document_type="foreign_resident_id",
                required_when_cel='has(request.nacionalidad) && request.nacionalidad != "PE"',
            ),
        ],
        rule_bindings=[
            RuleBinding(rule_id="semantic.attribute_consistency", severity=Severity.ERROR, blocking=True, on_fail="human_review"),
            RuleBinding(rule_id="batch.employee_name_matches_insured_name", severity=Severity.ERROR, blocking=True, on_fail="human_review"),
            RuleBinding(rule_id="self.payslip_arithmetic_consistency", severity=Severity.ERROR, blocking=True, on_fail="human_review"),
            RuleBinding(rule_id="self.loan_application_dni_format_valid", severity=Severity.ERROR, blocking=True, on_fail="human_review"),
            RuleBinding(rule_id="self.insurance_disclosure_dni_format_valid", severity=Severity.WARNING),
            RuleBinding(rule_id="self.authorization_letter_dni_format_valid", severity=Severity.WARNING),
            RuleBinding(rule_id="reference_data.employee_code_exists", severity=Severity.WARNING),
        ],
        thresholds=Thresholds(field_confidence_min=0.75),
    )


SEED_PROFILES = [
    (AD_HOC_KEY, "Ad-hoc", "Perfil integrado de la API heredada /batches: sin checklist, todas las reglas activas con su severidad por defecto.", ad_hoc_definition),
    ("convenios", "Préstamo por convenio", "Préstamo con descuento por planilla a trabajadores de una entidad con convenio.", convenios_definition),
]
