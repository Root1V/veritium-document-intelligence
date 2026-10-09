"""Semantic catalog (VRT-23, ADR-0007): a lightweight ontology of entities,
attributes, roles, and field→attribute mappings that gives extracted
document fields a shared business meaning.

Two documents that both map a field to ``titular.persona.dni`` can be
compared without anyone writing a pairwise cross-document rule, a profile
can require "evidence of income" satisfiable by any document type that maps
to ``ingreso.neto_mensual``, and consumers integrate against attribute keys
instead of per-document field names.

The catalog is versioned as a whole (``semantic_catalog_versions``) and is
immutable once published — a profile version pins one catalog version, so a
past case re-resolves identically.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

DataType = Literal["string", "number", "integer", "date", "boolean"]
# How two values of an attribute are judged equivalent during resolution
# (see domain/semantic_resolution.py). Kept separate from data_type: a DNI
# is a string but compares as an identifier (digits only, exact), a name is
# a string but compares fuzzily.
Comparison = Literal["identifier", "person_name", "company_name", "text", "number", "date"]
PiiClass = Literal["none", "personal", "sensitive"]

_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_ATTRIBUTE_KEY = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
# Top-level field ("client_dni") or one list hop into the first item
# ("persons[0].first_names") — enough for the 12 current schemas.
_FIELD_PATH = re.compile(r"^[a-z_][a-z0-9_]*(\[\d+\]\.[a-z_][a-z0-9_]*)?$")


class SemanticEntity(BaseModel):
    key: str
    name: str
    definition: str


class SemanticAttribute(BaseModel):
    key: str = Field(description="'<entity>.<name>', e.g. 'persona.dni'.")
    name: str
    definition: str
    data_type: DataType
    comparison: Comparison
    unit: str | None = None
    # CEL over `value` (the attribute's own value) — the intrinsic format
    # check; enforced as a validator in VRT-35, declared here so the
    # catalog is the single home of "what a valid DNI looks like".
    format_cel: str | None = None
    cardinality: Literal["one", "many"] = "one"
    pii_class: PiiClass = "none"
    # Relative tolerance for comparison="number" (0.01 = 1%).
    tolerance: float | None = None

    @property
    def entity(self) -> str:
        return self.key.split(".", 1)[0]

    @property
    def local_name(self) -> str:
        return self.key.split(".", 1)[1]


class SemanticRole(BaseModel):
    key: str
    name: str
    definition: str


class FieldMapping(BaseModel):
    document_type: str
    # A list concatenates the fields in order with a space — e.g. first
    # name + paternal + maternal surname → persona.nombre_completo.
    field_path: str | list[str]
    attribute: str
    role: str

    @property
    def field_paths(self) -> list[str]:
        return [self.field_path] if isinstance(self.field_path, str) else list(self.field_path)


class SemanticCatalog(BaseModel):
    entities: list[SemanticEntity]
    attributes: list[SemanticAttribute]
    roles: list[SemanticRole]
    mappings: list[FieldMapping]

    @model_validator(mode="after")
    def _check_integrity(self) -> SemanticCatalog:
        errors: list[str] = []
        entity_keys = _unique([e.key for e in self.entities], "entidad", errors)
        attribute_keys = _unique([a.key for a in self.attributes], "atributo", errors)
        role_keys = _unique([r.key for r in self.roles], "rol", errors)

        for key in entity_keys | role_keys:
            if not _KEY.match(key):
                errors.append(f"clave inválida '{key}' (minúsculas, dígitos y '_')")
        for attribute in self.attributes:
            if not _ATTRIBUTE_KEY.match(attribute.key):
                errors.append(f"atributo '{attribute.key}' debe tener la forma '<entidad>.<nombre>'")
            elif attribute.entity not in entity_keys:
                errors.append(f"atributo '{attribute.key}' referencia la entidad inexistente '{attribute.entity}'")
            if attribute.tolerance is not None and attribute.comparison != "number":
                errors.append(f"atributo '{attribute.key}': 'tolerance' solo aplica a comparison='number'")
            if attribute.format_cel:
                from idp.validation.cel import CelCompileError, compile_expression

                try:
                    compile_expression(attribute.format_cel)
                except CelCompileError as exc:
                    errors.append(f"atributo '{attribute.key}': format_cel no compila: {exc}")

        seen_targets: set[tuple[str, str, str]] = set()
        for m in self.mappings:
            if m.attribute not in attribute_keys:
                errors.append(f"mapeo {m.document_type}.{m.field_path}: atributo inexistente '{m.attribute}'")
            if m.role not in role_keys:
                errors.append(f"mapeo {m.document_type}.{m.field_path}: rol inexistente '{m.role}'")
            for path in m.field_paths:
                if not _FIELD_PATH.match(path):
                    errors.append(f"mapeo {m.document_type}: field_path inválido '{path}'")
            target = (m.document_type, m.role, m.attribute)
            if target in seen_targets:
                errors.append(f"{m.document_type} mapea dos veces a {m.role}.{m.attribute}")
            seen_targets.add(target)

        if errors:
            raise ValueError("; ".join(errors))
        return self

    def attribute(self, key: str) -> SemanticAttribute:
        for a in self.attributes:
            if a.key == key:
                return a
        raise KeyError(key)

    def mappings_for(self, document_type: str) -> list[FieldMapping]:
        return [m for m in self.mappings if m.document_type == document_type]

    def document_types_providing(self, attribute: str, role: str) -> set[str]:
        return {m.document_type for m in self.mappings if m.attribute == attribute and m.role == role}

    def content_hash(self) -> str:
        """sha256 over the canonical JSON — identical content, identical
        hash, regardless of key order on the way in."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _unique(keys: list[str], label: str, errors: list[str]) -> set[str]:
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            errors.append(f"{label} duplicado: '{key}'")
        seen.add(key)
    return seen


def read_field(payload: dict[str, Any], path: str) -> dict[str, Any] | None:
    """The ``Extracted`` envelope (as a dict) at ``path`` in an extraction
    payload, or None if absent/null. Supports 'field' and 'list[i].field'."""
    head, _, tail = path.partition(".")
    match = re.fullmatch(r"([a-z_][a-z0-9_]*)\[(\d+)\]", head)
    if match:
        items = payload.get(match.group(1))
        index = int(match.group(2))
        if not isinstance(items, list) or index >= len(items) or not isinstance(items[index], dict):
            return None
        envelope = items[index].get(tail)
    else:
        envelope = payload.get(path)
    if not isinstance(envelope, dict) or envelope.get("value") in (None, ""):
        return None
    return envelope


def field_meanings(catalog: SemanticCatalog, document_type: str) -> dict[str, str]:
    """What each field of a document type means to the business (VRT-46):
    the attribute it maps to, its definition and its role — what an
    extraction prompt can be grounded in."""
    attributes = {a.key: a for a in catalog.attributes}
    roles = {r.key: r.name for r in catalog.roles}
    meanings: dict[str, str] = {}
    for m in catalog.mappings:
        if m.document_type != document_type:
            continue
        attribute = attributes[m.attribute]
        for path in m.field_paths:
            meanings[path] = f"{attribute.name} del {roles.get(m.role, m.role).lower()}: {attribute.definition}"
    return meanings
