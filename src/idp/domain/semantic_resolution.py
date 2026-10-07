"""Per-case resolution over the semantic catalog (VRT-23): turns N documents'
extractions into one consolidated view — for each role and attribute, the
resolved value, whether the documents agree, and the evidence from every
source. Pure: no I/O, no LLM. Name comparison reuses the deterministic fuzzy
matcher from ``validation/entity_matching.py``; anything that would need an
LLM judge stays in the cross-document rules that already escalate.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from idp.domain.semantic import FieldMapping, SemanticAttribute, SemanticCatalog, read_field
from idp.validation.entity_matching import EntityKind, match_entities

ResolutionStatus = Literal["consistent", "conflict", "single_source"]

DEFAULT_NAME_MATCH_THRESHOLD = 0.90


class DocumentExtraction(BaseModel):
    """What resolution needs from one document: its type and its raw
    extraction payload (``Extracted`` envelopes as dicts)."""

    document_id: uuid.UUID
    document_type: str
    payload: dict[str, Any]


class EvidenceSource(BaseModel):
    document_id: uuid.UUID
    document_type: str
    field_path: str
    value: Any
    page: int | None = None
    bbox: list[float] | None = None
    confidence: float | None = None
    source_text: str | None = None


class ResolvedAttribute(BaseModel):
    role: str
    attribute: str
    value: Any
    status: ResolutionStatus
    # One entry per group of equivalent values; more than one means conflict.
    distinct_values: list[Any]
    sources: list[EvidenceSource]


class ConsolidatedView(BaseModel):
    catalog_version: int | None = None
    attributes: list[ResolvedAttribute]

    def get(self, role: str, attribute: str) -> ResolvedAttribute | None:
        for a in self.attributes:
            if a.role == role and a.attribute == attribute:
                return a
        return None

    def conflicts_involving(self, document_id: uuid.UUID) -> list[ResolvedAttribute]:
        return [a for a in self.attributes if a.status == "conflict" and any(s.document_id == document_id for s in a.sources)]

    def nested(self) -> dict[str, dict[str, dict[str, ResolvedAttribute]]]:
        """{role: {entity: {name: ResolvedAttribute}}} — the shape of the
        `entities` section of the result contract."""
        out: dict[str, dict[str, dict[str, ResolvedAttribute]]] = {}
        for a in self.attributes:
            entity, name = a.attribute.split(".", 1)
            out.setdefault(a.role, {}).setdefault(entity, {})[name] = a
        return out

    def as_cel(self) -> dict[str, Any]:
        """{role: {entity: {name: value}}} — exposed to CEL as `case`, so a
        rule can read `case.titular.persona.dni`. Conflicting attributes
        are exposed with their highest-confidence value; a rule that cares
        about consistency reads the finding, not the value."""
        return {
            role: {entity: {name: resolved.value for name, resolved in attrs.items()} for entity, attrs in entities.items()}
            for role, entities in self.nested().items()
        }


def resolve_case(
    catalog: SemanticCatalog,
    documents: list[DocumentExtraction],
    *,
    catalog_version: int | None = None,
    name_match_threshold: float = DEFAULT_NAME_MATCH_THRESHOLD,
) -> ConsolidatedView:
    sources_by_target: dict[tuple[str, str], list[EvidenceSource]] = {}
    for doc in documents:
        for mapping in catalog.mappings_for(doc.document_type):
            source = _source_for(doc, mapping)
            if source is not None:
                sources_by_target.setdefault((mapping.role, mapping.attribute), []).append(source)

    resolved: list[ResolvedAttribute] = []
    for (role, attribute_key), sources in sources_by_target.items():
        attribute = catalog.attribute(attribute_key)
        groups = _group_equivalent(attribute, sources, name_match_threshold)
        best = max(sources, key=lambda s: s.confidence if s.confidence is not None else 0.0)
        if len(sources) == 1:
            status: ResolutionStatus = "single_source"
        elif len(groups) == 1:
            status = "consistent"
        else:
            status = "conflict"
        resolved.append(
            ResolvedAttribute(
                role=role,
                attribute=attribute_key,
                value=best.value,
                status=status,
                distinct_values=[group[0].value for group in groups],
                sources=sources,
            )
        )
    resolved.sort(key=lambda a: (a.role, a.attribute))
    return ConsolidatedView(catalog_version=catalog_version, attributes=resolved)


def describe_conflict(resolved: ResolvedAttribute) -> str:
    parts = [f"'{s.value}' ({s.document_type})" for s in resolved.sources]
    return f"{resolved.role}.{resolved.attribute}: " + " vs ".join(parts)


def _source_for(doc: DocumentExtraction, mapping: FieldMapping) -> EvidenceSource | None:
    envelopes = [read_field(doc.payload, path) for path in mapping.field_paths]
    present = [(path, env) for path, env in zip(mapping.field_paths, envelopes) if env is not None]
    if not present:
        return None
    if len(mapping.field_paths) == 1:
        path, env = present[0]
        return EvidenceSource(
            document_id=doc.document_id,
            document_type=doc.document_type,
            field_path=path,
            value=env["value"],
            page=env.get("page"),
            bbox=env.get("bbox"),
            confidence=env.get("confidence"),
            source_text=env.get("source_text"),
        )
    # Concatenated mapping (e.g. first + paternal + maternal → full name):
    # value joins the parts present; evidence points at the first part and
    # carries the weakest confidence among them.
    confidences = [float(c) for _, env in present if (c := env.get("confidence")) is not None]
    first = present[0][1]
    return EvidenceSource(
        document_id=doc.document_id,
        document_type=doc.document_type,
        field_path="+".join(path for path, _ in present),
        value=" ".join(str(env["value"]).strip() for _, env in present),
        page=first.get("page"),
        bbox=first.get("bbox"),
        confidence=min(confidences) if confidences else None,
        source_text=" | ".join(str(env.get("source_text")) for _, env in present if env.get("source_text")) or None,
    )


def _group_equivalent(attribute: SemanticAttribute, sources: list[EvidenceSource], name_threshold: float) -> list[list[EvidenceSource]]:
    """Greedy single-linkage grouping: a source joins the first group whose
    representative it is equivalent to."""
    groups: list[list[EvidenceSource]] = []
    for source in sources:
        for group in groups:
            if _equivalent(attribute, group[0].value, source.value, name_threshold):
                group.append(source)
                break
        else:
            groups.append([source])
    return groups


def _equivalent(attribute: SemanticAttribute, a: Any, b: Any, name_threshold: float) -> bool:
    match attribute.comparison:
        case "identifier":
            return _digits_or_text(a) == _digits_or_text(b)
        case "person_name":
            return match_entities(EntityKind.PERSON, str(a), str(b), high_threshold=name_threshold, low_threshold=0.0).score >= name_threshold
        case "company_name":
            return match_entities(EntityKind.COMPANY, str(a), str(b), high_threshold=name_threshold, low_threshold=0.0).score >= name_threshold
        case "number":
            return _numbers_equal(a, b, attribute.tolerance or 0.0)
        case "date":
            return _as_date(a) == _as_date(b)
        case _:
            return _plain(a) == _plain(b)


def _plain(value: Any) -> str:
    nfkd = unicodedata.normalize("NFKD", str(value))
    return " ".join("".join(c for c in nfkd if not unicodedata.combining(c)).lower().split())


def _digits_or_text(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value))
    return digits if digits else _plain(value)


def _numbers_equal(a: Any, b: Any, tolerance: float) -> bool:
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return _plain(a) == _plain(b)
    if x == y:
        return True
    return abs(x - y) <= tolerance * max(abs(x), abs(y))


_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y")


def _as_date(value: Any) -> date | str:
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return _plain(text)
