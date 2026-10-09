"""Selective reprocessing (VRT-40): what a reprocess run redoes. A case or a
document is re-extracted and the whole case re-evaluated; a rule or an
attribute (or one corrected field) re-evaluates only the rules it reaches,
through what each rule declares it reads (ValidationRule.reads). Pure —
the API prepares the run and evaluate_case applies the scope."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, model_validator

from idp.domain.semantic import SemanticCatalog
from idp.validation.base import ValidationRule

ScopeKind = Literal["case", "document", "rule", "attribute"]


class ReprocessScope(BaseModel):
    kind: ScopeKind
    document_id: uuid.UUID | None = None
    # kind="attribute": a semantic attribute (every document contributing
    # it), or one field of one document (a correction).
    attribute: str | None = None
    field_path: str | None = None
    rule_id: str | None = None

    @model_validator(mode="after")
    def _target(self) -> ReprocessScope:
        if self.kind == "document" and self.document_id is None:
            raise ValueError("el alcance 'document' necesita document_id")
        if self.kind == "rule" and not self.rule_id:
            raise ValueError("el alcance 'rule' necesita rule_id")
        if self.kind == "attribute" and not self.attribute and not (self.document_id and self.field_path):
            raise ValueError("el alcance 'attribute' necesita attribute, o document_id y field_path")
        return self

    @property
    def reextracts(self) -> bool:
        return self.kind in ("case", "document")


def changed_reads(scope: ReprocessScope, catalog: SemanticCatalog | None, *, document_type: str | None) -> set[str]:
    """The ValidationRule.reads tokens an attribute-scoped reprocess
    touches: the field and the attributes it maps to, or the attribute and
    every field mapped to it."""
    mappings = catalog.mappings if catalog is not None else []
    if scope.field_path is not None:
        field = scope.field_path.split("[")[0].split(".")[0]
        attributes = {m.attribute for m in mappings if m.document_type == document_type and field in m.field_paths}
        return {field} | {f"@{a}" for a in attributes}
    fields = {path for m in mappings if m.attribute == scope.attribute for path in m.field_paths}
    return fields | {f"@{scope.attribute}"}


def _reaches(rule: ValidationRule, changed: set[str]) -> bool:
    if rule.reads is None:
        return True
    if "@*" in rule.reads and any(token.startswith("@") for token in changed):
        return True
    return bool(rule.reads & changed)


def rules_to_reevaluate(rules: list[ValidationRule], scope: ReprocessScope, changed: set[str]) -> list[ValidationRule]:
    """The rules a rule- or attribute-scoped run evaluates, plus the rules
    they depend on (their results feed the dependent rule)."""
    if scope.kind == "rule":
        selected = {r.rule_id for r in rules if r.rule_id == scope.rule_id}
    else:
        selected = {r.rule_id for r in rules if _reaches(r, changed)}
    by_id = {r.rule_id: r for r in rules}
    pending = list(selected)
    while pending:
        rule = by_id[pending.pop()]
        for dependency in rule.depends_on:
            if dependency in by_id and dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return [r for r in rules if r.rule_id in selected]
