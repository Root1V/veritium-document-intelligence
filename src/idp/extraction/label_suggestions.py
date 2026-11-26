"""Other names a field is printed under, read from recent documents of its
type (VRT-119): the label beside each value the extraction found. When an
issuer changes its template, the label changes before anything breaks; these
are the names to add to the field so the agent keeps finding it. A lookup in
the read text, no model: the place of each value is already known."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from pydantic import BaseModel

from idp.parsing.normalize import ParsedBlock, ParsedDocument

_MIN_DOCUMENTS = 2  # a label seen once may be noise
_MAX_LABEL = 40


class LabelSuggestion(BaseModel):
    field: str
    label: str
    documents: int


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _clean(label: str) -> str | None:
    label = re.sub(r"\s+", " ", label).strip(" :.-|")
    letters = sum(c.isalpha() for c in label)
    return label if 2 <= len(label) <= _MAX_LABEL and letters >= len(label) / 2 else None


def label_of(value: ParsedBlock, parsed: ParsedDocument) -> str | None:
    """The label printed with a value: in its own region before a colon, else the region on its left on the same line, else the one just above."""
    if ":" in value.text:
        own = _clean(value.text.split(":", 1)[0])
        if own:
            return own
    x1, y1, x2, y2 = value.bbox
    height = max(y2 - y1, 1e-6)
    same_page = [b for b in parsed.blocks if b.page == value.page and b.read and b.text.strip() and b.region_id != value.region_id]
    left = [b for b in same_page if b.bbox[2] <= x1 + 0.01 and min(y2, b.bbox[3]) - max(y1, b.bbox[1]) >= height / 2 and x1 - b.bbox[2] < 0.4]
    above = [b for b in same_page if b.bbox[3] <= y1 + 0.005 and y1 - b.bbox[3] < 0.04 and min(x2, b.bbox[2]) - max(x1, b.bbox[0]) > 0]
    for candidates, distance in ((left, lambda b: x1 - b.bbox[2]), (above, lambda b: y1 - b.bbox[3])):
        if candidates and (label := _clean(min(candidates, key=distance).text)):
            return label
    return None


def _envelopes(payload: dict):
    """Top-level read fields. Not a list's columns: beside each row's value is that row's name
    ('VPRI-65%'), not the column's; nor the summary, which the agent writes."""
    for name, value in payload.items():
        if name != "summary" and isinstance(value, dict) and "value" in value and value.get("bbox") is not None:
            yield name, value


def _values(payload: dict) -> set[str]:
    """Every value the document gave, to tell a label from the value of the field above (ID cards stack them)."""
    out: set[str] = set()
    for value in payload.values():
        if isinstance(value, dict) and "value" in value:
            out.add(_norm(str(value["value"])))
        elif isinstance(value, list):
            for item in value:
                out |= _values(item) if isinstance(item, dict) else set()
    return out


def suggest_labels(readings: list[tuple[dict, ParsedDocument]], known: dict[str, list[str]]) -> list[LabelSuggestion]:
    """``readings``: each recent document's extraction payload and read text;
    ``known``: per field, the names it already has (its aliases and the label
    its description quotes). Suggests what at least two documents print."""
    seen: dict[str, Counter[str]] = {}
    shown: dict[tuple[str, str], str] = {}
    for payload, parsed in readings:
        per_doc: set[tuple[str, str]] = set()
        values = _values(payload)
        for path, envelope in _envelopes(payload):
            block = next((b for b in parsed.blocks if b.page == envelope.get("page") and b.bbox == envelope["bbox"]), None)
            label = label_of(block, parsed) if block is not None else None
            if label and _norm(label) not in values:
                per_doc.add((path, _norm(label)))
                shown.setdefault((path, _norm(label)), label)
        for path, norm in per_doc:
            seen.setdefault(path, Counter())[norm] += 1
    out = []
    for path, counts in seen.items():
        names = [_norm(k) for k in known.get(path, [])]
        for norm, n in counts.most_common():
            if n >= _MIN_DOCUMENTS and not any(norm == k or norm in k for k in names if k):
                out.append(LabelSuggestion(field=path, label=shown[(path, norm)], documents=n))
    return sorted(out, key=lambda s: (-s.documents, s.field))
