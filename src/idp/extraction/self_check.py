"""Self-check of an extraction draft (VRT-67): before submitting, the
extraction agent runs on its draft the document's own rules — the same
ones validation will run afterwards: arithmetic within the document, the
format of each semantic attribute (e.g. a DNI is 8 digits) and the
document's own CEL rules (category SELF). What fails comes back in words,
so the agent re-reads and corrects; if the document really says so, it
submits anyway and validation reports it as always. Never a model call."""

from __future__ import annotations

import uuid
from typing import Any, get_args

from pydantic import BaseModel

from idp.domain.envelope import Extracted
from idp.domain.request_payload import RequestInputPayload
from idp.domain.semantic import SemanticCatalog
from idp.domain.semantic_resolution import DocumentExtraction, resolve_case
from idp.validation.base import RuleCategory, ValidationRule
from idp.validation.context import DocumentFields, ValidationContext
from idp.validation.engine import run_validation
from idp.validation.ports import InMemoryReferenceDataPort, StubExternalSystemPort


def _number_fields(schema: type[BaseModel]) -> set[str]:
    """The top-level fields whose value is a number — a draft may bring "3,497.20" for them."""
    out = set()
    for name, field in schema.model_fields.items():
        for candidate in (field.annotation, *get_args(field.annotation)):
            if isinstance(candidate, type) and issubclass(candidate, Extracted):
                value_type = candidate.model_fields["value"].annotation
                if value_type in (int, float) or {int, float} & set(get_args(value_type)):
                    out.add(name)
    return out


def _plain(value: Any) -> Any:
    """The value itself, when the agent passes the schema's envelope ({"value": ..., "page": ...})."""
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def _number(value: Any) -> Any:
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return value
    return value


class DraftChecker:
    def __init__(self, rules: list[ValidationRule], catalog: SemanticCatalog | None, document_type: str, schema: type[BaseModel]) -> None:
        self.rules = [r for r in rules if r.category == RuleCategory.SELF]
        self._catalog, self._type, self._numbers = catalog, document_type, _number_fields(schema)

    async def check(self, draft: dict[str, Any]) -> list[str]:
        """The problems the document's own rules find in ``draft`` — {field: value}, or
        {field: {"value": ...}} as the schema's envelopes come — in words. Never raises:
        a draft the rules cannot read is reported as such, and the agent goes on."""
        values = {k: (_number(v) if k in self._numbers else v) for k, v in ((k, _plain(v)) for k, v in draft.items()) if v not in (None, "")}
        document_id = uuid.uuid4()
        payload = {k: {"value": v} for k, v in values.items()}
        try:
            view = resolve_case(self._catalog, [DocumentExtraction(document_id=document_id, document_type=self._type, payload=payload)]) if self._catalog else None
            context = ValidationContext(
                case_id=uuid.uuid4(),
                current_document=DocumentFields(document_id=document_id, document_type=self._type, fields=values, payload=payload),
                sibling_documents=[],
                request_payload=RequestInputPayload(data={}),
                reference_data=InMemoryReferenceDataPort({}),
                external_system=StubExternalSystemPort(),
                semantic_view=view,
            )
            return [r.message for r in await run_validation(self.rules, context) if not r.passed]
        except Exception as exc:  # a value of the wrong kind, e.g. text where an amount goes
            return [f"No se pudo revisar el borrador ({type(exc).__name__}): revisa que cada valor tenga el tipo del esquema."]
