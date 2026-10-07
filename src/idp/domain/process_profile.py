"""Process profiles (VRT-24): how one business process (e.g. "Convenios",
"Contratación de tarjetas") uses Veritium — which documents or evidence a
case must bring, which rules apply and with what weight, and the thresholds
that decide automatic vs. human handling. Configured as data, versioned,
immutable once published; a case pins one profile version (VRT-25), and a
profile version pins one semantic catalog version (ADR-0007), so a past case
re-evaluates identically.

Two kinds of checklist requirement:
- by document type: "a loan application must be present";
- by semantic attribute: "evidence of the titular's net income must be
  present", satisfiable by any document type that maps to that attribute
  (payslip, debt capacity calculation, …) — alternative documents, which a
  per-type checklist cannot express.

Severity lives on the rule *binding*, not on the rule: the same rule can be
blocking in online contracting and only a warning for Risk.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from idp.domain.semantic import SemanticCatalog
from idp.validation.base import Severity

OnFail = Literal["human_review", "return_to_client"]

_KEY = re.compile(r"^[a-z][a-z0-9_-]*$")


class ChecklistItem(BaseModel):
    key: str = Field(description="Identificador estable del requisito dentro del perfil, p. ej. 'evidencia_ingreso'.")
    label: str = Field(description="Texto para personas, p. ej. 'Evidencia de ingreso del titular'.")
    document_type: str | None = Field(default=None, description="Requisito por tipo de documento.")
    requires_attributes: list[str] = Field(default_factory=list, description="Requisito por atributo semántico (p. ej. 'ingreso.neto_mensual').")
    role: str = Field(default="titular", description="Rol semántico del requisito por atributo.")
    accepted_document_types: list[str] | None = Field(
        default=None, description="Restringe qué tipos pueden satisfacer un requisito por atributo. None = cualquiera que lo mapee."
    )
    required: bool = True
    required_when_cel: str | None = Field(
        default=None, description="CEL sobre `request` (datos del proceso) y `case` (vista semántica). Si es falso, el requisito no aplica."
    )
    min_count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _one_kind(self) -> ChecklistItem:
        by_type, by_attribute = self.document_type is not None, bool(self.requires_attributes)
        if by_type == by_attribute:
            raise ValueError(f"requisito '{self.key}': debe ser por tipo de documento o por atributo, no ambos ni ninguno")
        if by_type and self.accepted_document_types is not None:
            raise ValueError(f"requisito '{self.key}': accepted_document_types solo aplica a requisitos por atributo")
        return self


class RuleBinding(BaseModel):
    rule_id: str
    severity: Severity = Severity.WARNING
    blocking: bool = Field(default=False, description="Si falla, determina el veredicto (según on_fail).")
    on_fail: OnFail = "human_review"


class Thresholds(BaseModel):
    field_confidence_min: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confianza mínima por campo; por debajo, revisión humana. None = el valor global."
    )


class ProcessProfileDefinition(BaseModel):
    semantic_catalog_version: int = Field(ge=1)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    # True = every active rule applies with its default severity (the
    # built-in 'ad-hoc' profile, i.e. v0.3.0 behaviour); rule_bindings then
    # only override. False = only the bound rules run.
    include_all_rules: bool = False
    rule_bindings: list[RuleBinding] = Field(default_factory=list)
    thresholds: Thresholds = Field(default_factory=Thresholds)

    @model_validator(mode="after")
    def _intrinsic(self) -> ProcessProfileDefinition:
        errors: list[str] = []
        keys = [c.key for c in self.checklist]
        for key in keys:
            if not _KEY.match(key):
                errors.append(f"clave de requisito inválida '{key}'")
        for dup in {k for k in keys if keys.count(k) > 1}:
            errors.append(f"requisito duplicado '{dup}'")
        rule_ids = [b.rule_id for b in self.rule_bindings]
        for dup in {r for r in rule_ids if rule_ids.count(r) > 1}:
            errors.append(f"regla vinculada dos veces '{dup}'")
        for item in self.checklist:
            if item.required_when_cel:
                from idp.validation.cel import CelCompileError, compile_expression

                try:
                    compile_expression(item.required_when_cel)
                except CelCompileError as exc:
                    errors.append(f"requisito '{item.key}': required_when_cel no compila: {exc}")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def content_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def binding_for(self, rule_id: str) -> RuleBinding | None:
        for b in self.rule_bindings:
            if b.rule_id == rule_id:
                return b
        return None


def cross_reference_errors(
    definition: ProcessProfileDefinition,
    *,
    catalog: SemanticCatalog,
    known_document_types: set[str],
    known_rule_ids: set[str],
) -> list[str]:
    """What a definition references must exist: document types, semantic
    attributes and roles (in the pinned catalog version), and rule ids. An
    attribute requirement restricted to types that don't map the attribute
    could never be satisfied, so that is an error too. Pure — the caller
    loads the catalog and the known ids."""
    errors: list[str] = []
    attribute_keys = {a.key for a in catalog.attributes}
    role_keys = {r.key for r in catalog.roles}
    for item in definition.checklist:
        if item.document_type is not None and item.document_type not in known_document_types:
            errors.append(f"requisito '{item.key}': tipo de documento desconocido '{item.document_type}'")
        if not item.requires_attributes:
            continue
        if item.role not in role_keys:
            errors.append(f"requisito '{item.key}': rol desconocido '{item.role}' en el catálogo v{definition.semantic_catalog_version}")
        for attribute in item.requires_attributes:
            if attribute not in attribute_keys:
                errors.append(f"requisito '{item.key}': atributo desconocido '{attribute}' en el catálogo v{definition.semantic_catalog_version}")
                continue
            providers = catalog.document_types_providing(attribute, item.role)
            if item.accepted_document_types is not None:
                for doc_type in item.accepted_document_types:
                    if doc_type not in known_document_types:
                        errors.append(f"requisito '{item.key}': tipo de documento desconocido '{doc_type}'")
                providers &= set(item.accepted_document_types)
            if not providers:
                errors.append(f"requisito '{item.key}': ningún tipo de documento aceptado mapea {item.role}.{attribute}; nunca se podría satisfacer")
    for binding in definition.rule_bindings:
        if binding.rule_id not in known_rule_ids:
            errors.append(f"regla desconocida '{binding.rule_id}'")
    return errors
