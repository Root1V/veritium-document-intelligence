"""Masking of a case's personal data (VRT-58), derived from the semantic
catalog's ``pii_class``: what anyone sees by default, until someone who works
the case asks to see it (and that is recorded).

The masker knows the case's values, not the shape of each response. It is
built from the case's extractions — each field's class comes from the
mapping of its document type to a semantic attribute — and then masks any
response about the case: the values themselves, and those same values
quoted inside finding messages, verdict reasons, the OCR text that is the
evidence, or an error. One dictionary, so a new response or a new message
cannot forget a field.

- ``sensitive`` (income, amounts of a person): hidden, ``•••``.
- ``personal`` (identity, contact): partly shown — the last four digits of a
  number like a DNI, the initials of a name — enough to tell two apart.
- A field no mapping classifies counts as ``personal``: a new document type
  is private until someone says otherwise. ``none`` is shown as is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from idp.domain.semantic import SemanticCatalog

HIDDEN = "•••"
# Response keys whose number is a datum of the case (and not a count or a confidence).
_VALUE_KEYS = {"value", "values", "expected", "actual", "current_value", "original_value", "corrected_value", "suggested_value", "distinct_values"}
_INDEX = re.compile(r"\[\d+\]")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_RANK = {"none": 0, "personal": 1, "sensitive": 2}


def mask_value(value: Any, pii_class: str) -> Any:
    """One datum, masked for its class."""
    if pii_class == "none" or value is None or isinstance(value, bool):
        return value
    if pii_class == "sensitive" or isinstance(value, (int, float)):
        return HIDDEN
    if isinstance(value, list):
        return [mask_value(v, pii_class) for v in value]
    if isinstance(value, dict):
        return {k: mask_value(v, pii_class) for k, v in value.items()}
    text = str(value).strip()
    compact = re.sub(r"\s", "", text)  # a DNI or a phone, maybe spaced; a date keeps its separators
    if compact.isdigit():
        return "••••" + compact[-4:] if len(compact) > 4 else HIDDEN
    if any(ch.isdigit() for ch in text) or "@" in text:  # dates, addresses, e-mails
        return HIDDEN
    words = [w for w in re.split(r"[\s,]+", text) if w]
    return " ".join(f"{w[0].upper()}." for w in words[:4]) if words else HIDDEN


class Masker:
    """Masks every response about one case. ``Masker.clear()`` masks nothing:
    what someone sees after asking to see the data."""

    def __init__(self, secrets: dict[str, str] | None = None, numbers: set[float] | None = None, *, active: bool = True) -> None:
        self.active = active
        self._numbers = numbers or set()
        # Longest first, so "SALAS SIGUAS KATERIN" goes before "SALAS".
        self._secrets = sorted((secrets or {}).items(), key=lambda kv: -len(kv[0]))
        alternatives = "|".join(re.escape(s) for s, _ in self._secrets)
        self._pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE) if self._secrets else None
        self._masked = {s.casefold(): m for s, m in self._secrets}

    @classmethod
    def clear(cls) -> Masker:
        return cls(active=False)

    @classmethod
    def for_documents(cls, catalog: SemanticCatalog | None, documents: Iterable[tuple[str | None, dict | None]], extra: Iterable[Any] = ()) -> Masker:
        """From the case's extractions — (document type, payload) — and other personal values (the process data)."""
        found: dict[str, tuple[Any, str]] = {}  # text → (value, class)
        numbers: set[float] = set()

        def keep(value: Any, pii_class: str) -> None:
            if pii_class == "none" or value is None or isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                if abs(value) >= 10:  # not a 1 or a 0 that is everywhere
                    numbers.add(round(float(value), 2))
                    for text in (str(value), f"{value:,.2f}", f"{value:.2f}"):
                        found.setdefault(text, (value, "sensitive"))
                return
            if isinstance(value, (list, dict)):
                for v in value.values() if isinstance(value, dict) else value:
                    keep(v, pii_class)
                return
            text = str(value).strip()
            if len(text) < 3:
                return
            if _RANK[pii_class] > _RANK[found.get(text, (None, "none"))[1]]:
                found[text] = (text, pii_class)
            if not any(ch.isdigit() for ch in text):  # a name also appears word by word, in any order
                for word in re.split(r"[\s,]+", text):
                    if len(word) >= 4:
                        found.setdefault(word, (word, pii_class))

        for document_type, payload in documents:
            for path, envelope in _fields(payload or {}):
                keep(envelope.get("value") if isinstance(envelope, dict) and "value" in envelope else envelope, _class_of(catalog, document_type, path))
        for value in extra:
            keep(value, "personal")
        secrets = {text: mask_value(value, cls_) if cls_ != "sensitive" else HIDDEN for text, (value, cls_) in found.items()}
        return cls(secrets, numbers)

    def text(self, text: str) -> str:
        if not self.active or self._pattern is None or not text:
            return text
        return self._pattern.sub(lambda m: self._masked.get(m.group(0).casefold(), HIDDEN), text)

    def json(self, data: Any, *, _key: str | None = None) -> Any:
        """A whole response (dicts, lists, strings, numbers), masked."""
        if not self.active:
            return data
        if isinstance(data, dict):
            return {k: self.json(v, _key=k) for k, v in data.items()}
        if isinstance(data, list):
            return [self.json(v, _key=_key) for v in data]
        if isinstance(data, str):
            return data if _UUID.fullmatch(data) else self.text(data)  # an id is never a datum
        if isinstance(data, (int, float)) and not isinstance(data, bool) and _key in _VALUE_KEYS and round(float(data), 2) in self._numbers:
            return HIDDEN
        return data


def _class_of(catalog: SemanticCatalog | None, document_type: str | None, path: str) -> str:
    """A field's class: its semantic attribute's, by the mapping of its document
    type (any list index matches); unmapped, ``personal``."""
    if catalog is not None:
        general = _INDEX.sub("[0]", path)
        for mapping in catalog.mappings:
            if mapping.document_type == document_type and general in (_INDEX.sub("[0]", p) for p in mapping.field_paths):
                return catalog.attribute(mapping.attribute).pii_class
    return "personal"


def _fields(payload: dict | list, prefix: str = "") -> Iterable[tuple[str, Any]]:
    """(path, envelope) of every field: top-level, and each item of a list of objects."""
    if isinstance(payload, list):  # e.g. an evaluation's per-field results
        for i, item in enumerate(payload):
            yield from _fields(item, f"{prefix}[{i}].") if isinstance(item, (dict, list)) else [(f"{prefix}[{i}]", item)]
        return
    for name, node in payload.items():
        path = f"{prefix}{name}"
        if isinstance(node, list):
            for i, item in enumerate(node):
                if isinstance(item, dict) and "value" not in item:
                    yield from _fields(item, f"{path}[{i}].")
                else:
                    yield f"{path}[{i}]", item
        elif isinstance(node, dict) and "value" not in node and node and all(isinstance(v, dict) for v in node.values()):
            yield from _fields(node, f"{path}.")
        else:
            yield path, node
