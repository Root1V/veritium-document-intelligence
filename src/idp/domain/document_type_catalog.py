"""Document types as versioned data (VRT-32, ADR-0008).

A type is its definition: the name users see, the description the
classifier reads, the hint the extraction agent reads, and the target
schema. The schema is data — fields of ``str | int | float | bool | enum``,
each wrapped in ``Extracted[T]`` at runtime, plus one level of lists of
sub-objects — and is compiled into a Pydantic model when a run needs it,
because extraction, grounding and review routing work on real ``Extracted``
instances. Field descriptions matter: they are what the model sees.

``generic`` is not in the catalog: it is a strategy (one best-effort call,
always reviewed), not a schema, and stays in code."""

from __future__ import annotations

import hashlib
import json
import re
import types
import typing
from functools import lru_cache
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, create_model, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from idp.domain.envelope import Extracted

GENERIC = "generic"
_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
_CLASS = re.compile(r"^[A-Z][A-Za-z0-9]*$")
ValueType = Literal["str", "int", "float", "bool", "enum"]
_PY_TYPES: dict[str, type] = {"str": str, "int": int, "float": float, "bool": bool}


class FieldSpec(BaseModel):
    name: str
    type: Literal["str", "int", "float", "bool", "enum", "list"]
    required: bool = False
    description: str | None = None
    enum_values: list[str] | None = None
    # False: a plain value (e.g. a label the model names), not an
    # Extracted[T] with page/bbox/confidence.
    grounded: bool = True
    # type == "list": a list of sub-objects, one level deep.
    item_name: str | None = None
    item_description: str | None = None
    items: list[FieldSpec] | None = None

    @model_validator(mode="after")
    def _shape(self) -> FieldSpec:
        if not _SNAKE.match(self.name):
            raise ValueError(f"campo '{self.name}': el nombre debe ser snake_case")
        if (self.type == "enum") != bool(self.enum_values):
            raise ValueError(f"campo '{self.name}': enum_values va solo con type 'enum', y no vacío")
        if self.type == "list":
            if not self.items or not self.item_name or not _CLASS.match(self.item_name):
                raise ValueError(f"campo '{self.name}': una lista necesita items e item_name en CamelCase")
            if self.required:
                raise ValueError(f"campo '{self.name}': una lista no es obligatoria (vacía es un valor válido)")
            if any(i.type == "list" for i in self.items):
                raise ValueError(f"campo '{self.name}': solo un nivel de listas")
            _unique([i.name for i in self.items], f"items de '{self.name}'")
        elif self.items or self.item_name or self.item_description:
            raise ValueError(f"campo '{self.name}': items/item_name solo van con type 'list'")
        if self.type == "list" and not self.grounded:
            raise ValueError(f"campo '{self.name}': 'grounded' no aplica a una lista")
        return self


class DocumentTypeDefinition(BaseModel):
    key: str
    display_name: str
    description: str = Field(description="Qué es el documento; lo lee el clasificador.")
    extraction_hint: str = Field(default="", description="Pistas para el agente de extracción.")
    schema_title: str
    schema_description: str | None = None
    fields: list[FieldSpec]

    @model_validator(mode="after")
    def _shape(self) -> DocumentTypeDefinition:
        if not _SNAKE.match(self.key) or self.key == GENERIC:
            raise ValueError(f"clave '{self.key}': snake_case, y '{GENERIC}' está reservada")
        if not _CLASS.match(self.schema_title):
            raise ValueError("schema_title debe ser CamelCase")
        if not self.fields:
            raise ValueError("el esquema necesita al menos un campo")
        _unique([f.name for f in self.fields], "campos")
        return self

    def content_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def field_paths(self) -> set[str]:
        """What a semantic mapping may point at: ``field`` and ``list[i].field``."""
        paths: set[str] = set()
        for f in self.fields:
            if f.type == "list":
                paths |= {f"{f.name}[].{i.name}" for i in f.items or []}
            else:
                paths.add(f.name)
        return paths


def _unique(names: list[str], what: str) -> None:
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise ValueError(f"{what} repetidos: {duplicated}")


# --- compile: definition -> Pydantic model --------------------------------


def _value_type(spec: FieldSpec) -> Any:
    return Literal[tuple(spec.enum_values or ())] if spec.type == "enum" else _PY_TYPES[spec.type]


def _model(name: str, doc: str | None, specs: list[FieldSpec]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for spec in specs:
        if spec.type == "list":
            item = _model(spec.item_name or "", spec.item_description, spec.items or [])
            fields[spec.name] = (list[item], Field(default_factory=list, description=spec.description))  # type: ignore[valid-type]
            continue
        value = Extracted[_value_type(spec)] if spec.grounded else _value_type(spec)  # type: ignore[misc]
        if spec.required:
            fields[spec.name] = (value, Field(description=spec.description))
        else:
            fields[spec.name] = (value | None, Field(default=None, description=spec.description))
    return create_model(name, __doc__=doc, **fields)


@lru_cache(maxsize=256)
def _compile(definition_json: str) -> type[BaseModel]:
    d = DocumentTypeDefinition.model_validate_json(definition_json)
    return _model(d.schema_title, d.schema_description, d.fields)


def compile_schema(definition: DocumentTypeDefinition) -> type[BaseModel]:
    """The extraction schema for a type version. Cached by content: a
    published version never changes, so it compiles once per process."""
    return _compile(definition.model_dump_json())


# --- seed: Pydantic class -> definition ------------------------------------


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    if typing.get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1 and len(typing.get_args(annotation)) == 2:
            return True, args[0]
    return False, annotation


def _spec(name: str, info: FieldInfo) -> FieldSpec:
    optional, annotation = _is_optional(info.annotation)
    description = info.description
    if typing.get_origin(annotation) is list:
        (item,) = typing.get_args(annotation)
        return FieldSpec(
            name=name,
            type="list",
            description=description,
            item_name=item.__name__,
            item_description=item.__doc__,
            items=[_spec(n, i) for n, i in item.model_fields.items()],
        )
    grounded = isinstance(annotation, type) and issubclass(annotation, Extracted)
    if not grounded and annotation not in _PY_TYPES.values() and typing.get_origin(annotation) is not Literal:
        raise TypeError(f"campo '{name}': solo Extracted[T], un valor simple o list[SubModel] ({annotation!r})")
    value = annotation.model_fields["value"].annotation if grounded else annotation
    if typing.get_origin(value) is Literal:
        kind, enum_values = "enum", [str(v) for v in typing.get_args(value)]
    else:
        kind, enum_values = {v: k for k, v in _PY_TYPES.items()}[value], None
    required = not optional and info.default is PydanticUndefined and info.default_factory is None
    return FieldSpec(name=name, type=kind, required=required, description=description, enum_values=enum_values, grounded=grounded)


def definition_from_model(
    model: type[BaseModel], *, key: str, display_name: str, description: str, extraction_hint: str = ""
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        key=key,
        display_name=display_name,
        description=description,
        extraction_hint=extraction_hint,
        schema_title=model.__name__,
        schema_description=model.__doc__,
        fields=[_spec(n, i) for n, i in model.model_fields.items()],
    )


# --- a run's view of the catalog -------------------------------------------


class DocumentTypeCatalog:
    """The published types as a run sees them: the current version of each
    type, plus every version that ever produced an extraction (published or
    retired), so a stored payload is re-read with the schema that made it."""

    def __init__(self, versions: list[tuple[str, int, str, DocumentTypeDefinition]]) -> None:
        # (key, version, status, definition)
        self._by_version = {(k, v): d for k, v, _, d in versions}
        current: dict[str, tuple[int, DocumentTypeDefinition]] = {}
        for key, version, status, definition in versions:
            if status == "published" and version >= current.get(key, (0, None))[0]:
                current[key] = (version, definition)
        self._current = current

    def keys(self) -> list[str]:
        return sorted(self._current)

    def current(self, key: str) -> tuple[int, DocumentTypeDefinition] | None:
        return self._current.get(key)

    def definition(self, key: str, version: int) -> DocumentTypeDefinition | None:
        return self._by_version.get((key, version))

    def schema(self, key: str, version: int) -> type[BaseModel] | None:
        definition = self.definition(key, version)
        return compile_schema(definition) if definition is not None else None
