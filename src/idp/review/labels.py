"""What a reviewer reads instead of a raw field path (``employee_code``,
``fields[15].value``, ``concepts[2].amount``): the semantic attribute the
field feeds and its role when the catalog maps it, else the document type's
own field, else the key a generic extraction gave it. Pure — the review
route loads the catalogs and the payload."""

from __future__ import annotations

import re

from pydantic import BaseModel

from idp.domain.document_type_catalog import GENERIC, DocumentTypeDefinition
from idp.domain.semantic import SemanticCatalog

_PATH = re.compile(r"^(?P<field>\w+)(?:\[(?P<index>\d+)\]\.(?P<sub>\w+))?$")


class FieldLabel(BaseModel):
    label: str
    description: str | None = None
    attribute: str | None = None  # 'persona.codigo_empleado'
    role: str | None = None  # 'Titular'


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def describe_field(
    field_path: str,
    *,
    document_type: str | None,
    definition: DocumentTypeDefinition | None,
    catalog: SemanticCatalog | None,
    payload: dict | None,
) -> FieldLabel:
    match = _PATH.match(field_path)
    if match is None:
        return FieldLabel(label=field_path)
    field, index, sub = match.group("field", "index", "sub")

    if document_type == GENERIC and field == "fields" and index is not None:
        entries = (payload or {}).get("fields") or []
        key = entries[int(index)].get("key") if int(index) < len(entries) else None
        return FieldLabel(
            label=_humanize(key) if key else f"Campo {int(index) + 1}",
            description="Dato detectado en un documento sin tipo registrado.",
        )

    if catalog is not None and index is None:
        mapping = next(
            (m for m in catalog.mappings if m.document_type == document_type and field_path in m.field_paths),
            None,
        )
        if mapping is not None:
            # The catalog's integrity check guarantees both exist.
            attribute = next(a for a in catalog.attributes if a.key == mapping.attribute)
            role = next(r for r in catalog.roles if r.key == mapping.role)
            return FieldLabel(
                label=attribute.name,
                description=attribute.definition,
                attribute=attribute.key,
                role=role.name,
            )

    spec = next((f for f in definition.fields if f.name == field), None) if definition else None
    if index is None:
        return FieldLabel(label=_humanize(field), description=spec.description if spec else None)
    item = next((i for i in spec.items or [] if i.name == sub), None) if spec else None
    return FieldLabel(
        label=f"{_humanize(sub)} — {_humanize(field).lower()} #{int(index) + 1}",
        description=(item.description if item else None) or (spec.item_description if spec else None),
    )
