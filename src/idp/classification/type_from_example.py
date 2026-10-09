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
from idp.llm.port import structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument

LeafType = Literal["str", "int", "float", "bool", "enum"]


class DraftLeaf(BaseModel):
    name: str = Field(description="snake_case en ingles.")
    type: LeafType
    required: bool = Field(description="True solo si este tipo de documento siempre lo trae.")
    description: str = Field(description="En español, explicita: que representa y donde aparece en el documento. Es lo unico que vera el agente de extraccion.")
    enum_values: list[str] | None = Field(default=None, description="Solo si type es 'enum': los valores posibles.")


class DraftField(DraftLeaf):
    type: Literal["str", "int", "float", "bool", "enum", "list"]  # type: ignore[assignment]
    item_name: str | None = Field(default=None, description="Solo si type es 'list': nombre CamelCase de cada elemento (p. ej. 'ConsumptionLine').")
    items: list[DraftLeaf] | None = Field(default=None, description="Solo si type es 'list': los campos de cada elemento.")


class DraftMapping(BaseModel):
    field_path: str = Field(description="Campo del nuevo tipo: 'campo' o 'lista[0].campo'.")
    attribute: str = Field(description="Clave de un atributo del catalogo semantico (lista dada).")
    role: str = Field(description="Clave de un rol del catalogo semantico (lista dada).")


class TypeDraft(BaseModel):
    similar_existing_type: str | None = Field(
        default=None, description="Si el documento es en realidad un tipo ya existente (lista dada), su clave; si no, null."
    )
    key: str = Field(description="snake_case en ingles, p. ej. 'electricity_bill'.")
    display_name: str = Field(description="Nombre legible en español, p. ej. 'Recibo de luz'.")
    description: str = Field(description="Que es este documento y como distinguirlo de los tipos parecidos; lo lee el clasificador.")
    extraction_hint: str = Field(description="Pistas breves para el agente de extraccion: donde suelen estar los datos, ambigüedades a evitar.")
    schema_title: str = Field(description="CamelCase terminado en 'Schema', p. ej. 'ElectricityBillSchema'.")
    fields: list[DraftField]
    mappings: list[DraftMapping] = Field(default_factory=list, description="Solo campos que significan exactamente un atributo del catalogo.")
    rationale: str = Field(description="Por que estos campos, y en que se distingue de los tipos existentes.")

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


_SYSTEM_PROMPT = prompt("propose_type_from_example", """Eres un analista que define tipos de documento para una plataforma de validacion \
documental. Recibes el texto (OCR) de UN documento de ejemplo y diseñas su tipo: un esquema de campos \
que sirva para cualquier documento de esa misma clase, aunque cambie el formato.

Reglas del esquema:
- Campos en snake_case ingles; type entre str, int, float, bool, enum o list.
- Fechas, codigos, documentos de identidad y montos con formato van como str; montos numericos como float.
- Una lista (type 'list') es para tablas o items repetidos; sus elementos tienen campos simples (sin listas dentro).
- required=True solo si el campo esta siempre presente en esta clase de documento.
- Incluye un campo opcional 'summary' (str): resumen breve del documento.
- Cada descripcion debe decir que es el campo y donde aparece: el agente de extraccion solo ve eso.
- No inventes campos que este tipo de documento no trae.

Tipos ya existentes (si el ejemplo es uno de estos, indicalo en similar_existing_type y aun asi propon el esquema):
{types}

Catalogo semantico — mapea un campo SOLO si significa exactamente uno de estos atributos, con el rol que \
corresponde (p. ej. el DNI del titular del recibo -> persona.dni con rol titular):
Atributos:
{attributes}
Roles:
{roles}""", filled=('types', 'attributes', 'roles'))


def propose_type_from_example(
    settings: Settings, parsed: ParsedDocument, *, type_catalog: DocumentTypeCatalog, semantic: SemanticCatalog, name_hint: str | None = None
) -> TypeDraft:
    types = "\n".join(f"- {k}: {type_catalog.current(k)[1].description}" for k in type_catalog.keys())  # type: ignore[index]
    attributes = "\n".join(f"- {a.key} ({a.data_type}): {a.definition}" for a in semantic.attributes)
    roles = "\n".join(f"- {r.key}: {r.definition}" for r in semantic.roles)
    task = f"Texto del documento de ejemplo:\n\n{parsed.full_text[:8000]}"
    if name_hint:
        task = f"El usuario lo llama: {name_hint}\n\n{task}"
    with traced_llm_call(role="reasoning", model=settings.reasoning_model):
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
