"""A new document type from one example document (VRT-33): the model
reads the example and drafts the whole type — its schema, the texts the
classifier and the extraction agent will read, and which of its fields mean
attributes the semantic catalog already knows. A person reviews and edits
the draft before anything is registered (api/routes/document_types.py).

This evolves VRT-03 (type discovery), which only proposed a name and a flat
field list: here the draft is a complete ``DocumentTypeDefinition``, so
accepting it is registering it."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from idp.config import Settings
from idp.domain.document_type_catalog import DocumentTypeCatalog, DocumentTypeDefinition, FieldSpec
from idp.domain.semantic import SemanticCatalog
from idp.llm.port import model_for, structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument

LeafType = Literal["str", "int", "float", "bool", "enum"]


class DraftLeaf(BaseModel):
    name: str = Field(description="English snake_case.")
    label: str = Field(description="How a person would name it, in Spanish and short, e.g. 'DNI del socio'.")
    type: LeafType
    required: bool = Field(description="True only if this type of document always carries it.")
    description: str = Field(description="In Spanish, explicit: what it represents and where it appears in the document. It is all the extraction agent will see.")
    enum_values: list[str] | None = Field(default=None, description="Only if type is 'enum': the possible values.")


class DraftField(DraftLeaf):
    type: Literal["str", "int", "float", "bool", "enum", "list"]  # type: ignore[assignment]
    item_name: str | None = Field(default=None, description="Only if type is 'list': CamelCase name of each item (e.g. 'ConsumptionLine').")
    items: list[DraftLeaf] | None = Field(default=None, description="Only if type is 'list': the fields of each item.")


class DraftMapping(BaseModel):
    field_path: str = Field(description="Field of the new type: 'field' or 'list[0].field'.")
    attribute: str = Field(description="Key of an attribute of the semantic catalog (list given).")
    role: str = Field(description="Key of a role of the semantic catalog (list given).")


class TypeDraft(BaseModel):
    similar_existing_type: str | None = Field(
        default=None, description="If the document is actually an existing type (list given), its key; otherwise null."
    )
    key: str = Field(description="English snake_case, e.g. 'electricity_bill'.")
    display_name: str = Field(description="Readable name in Spanish, e.g. 'Recibo de luz'.")
    description: str = Field(description="In Spanish: what this document is and how to tell it from similar types; the classifier reads it.")
    extraction_hint: str = Field(description="In Spanish: brief hints for the extraction agent: where the data usually is, ambiguities to avoid.")
    schema_title: str = Field(description="CamelCase ending in 'Schema', e.g. 'ElectricityBillSchema'.")
    fields: list[DraftField]
    mappings: list[DraftMapping] = Field(default_factory=list, description="Only fields that mean exactly one attribute of the catalog.")
    rationale: str = Field(description="In Spanish: why these fields, and how it differs from the existing types.")

    @model_validator(mode="after")
    def _a_valid_definition(self) -> TypeDraft:
        self.definition()  # raises with the reason, which synaptum shows the model before asking again
        return self

    def definition(self) -> DocumentTypeDefinition:
        return DocumentTypeDefinition(
            key=self.key,
            display_name=self.display_name,
            description=self.description,
            extraction_hint=self.extraction_hint,
            schema_title=self.schema_title,
            fields=[FieldSpec.model_validate(f.model_dump(exclude_none=True)) for f in self.fields],
        )


_SYSTEM_PROMPT = prompt("propose_type_from_example", """You are an analyst who defines document types for a document validation platform. You \
receive the text (OCR) of ONE example document and design its type: a field schema that works for any document of \
that same class, even if its layout changes.

Schema rules:
- Field names in English snake_case; type is one of str, int, float, bool, enum or list.
- Every field has a label: its name in Spanish, short, as a person would read it (e.g. 'DNI del socio', 'Fecha de emisión').
- Dates, codes, identity document numbers and formatted amounts are str; numeric amounts are float.
- A list (type 'list') is for tables or repeated items; its items have simple fields (no nested lists).
- required=True only if the field is always present in this class of document.
- Include an optional 'summary' field (str): a brief summary of the document.
- Each description, in Spanish, must say what the field is and where it appears: the extraction agent only sees that.
- Do not invent fields this type of document does not carry.
- display_name, description, extraction_hint and rationale are written in Spanish: people read them.

Existing types (if the example is one of these, say so in similar_existing_type and still propose the schema):
{types}

Semantic catalog — map a field ONLY if it means exactly one of these attributes, with the matching role \
(e.g. the DNI of the bill holder -> persona.dni with role titular):
Attributes:
{attributes}
Roles:
{roles}""", filled=('types', 'attributes', 'roles'))


def propose_type_from_example(
    settings: Settings, parsed: ParsedDocument, *, type_catalog: DocumentTypeCatalog, semantic: SemanticCatalog, name_hint: str | None = None
) -> TypeDraft:
    types = "\n".join(f"- {k}: {type_catalog.current(k)[1].description}" for k in type_catalog.keys())  # type: ignore[index]
    attributes = "\n".join(f"- {a.key} ({a.data_type}): {a.definition}" for a in semantic.attributes)
    roles = "\n".join(f"- {r.key}: {r.definition}" for r in semantic.roles)
    task = f"Text of the example document:\n\n{parsed.full_text[:8000]}"
    if name_hint:
        task = f"The user calls it: {name_hint}\n\n{task}"
    with traced_llm_call(role="reasoning", model=model_for("reasoning")):
        return structured(
            purpose="propose_type_from_example",
            role="reasoning",
            output=TypeDraft,
            instructions=_SYSTEM_PROMPT.render(types=types, attributes=attributes, roles=roles),
            task=task,
        )


def checked_mappings(definition: DocumentTypeDefinition, mappings: list[DraftMapping], semantic: SemanticCatalog) -> tuple[list[DraftMapping], list[str]]:
    """Keep the mappings the catalog can accept; say why the others were dropped."""
    paths = definition.field_paths()
    attributes, roles = {a.key for a in semantic.attributes}, {r.key for r in semantic.roles}
    kept, dropped = [], []
    for m in mappings:
        if re.sub(r"\[\d+\]", "[]", m.field_path) not in paths:
            dropped.append(f"{m.field_path}: no es un campo del esquema propuesto")
        elif m.attribute not in attributes:
            dropped.append(f"{m.field_path}: el atributo '{m.attribute}' no existe en el catálogo")
        elif m.role not in roles:
            dropped.append(f"{m.field_path}: el rol '{m.role}' no existe en el catálogo")
        else:
            kept.append(m)
    return kept, dropped
