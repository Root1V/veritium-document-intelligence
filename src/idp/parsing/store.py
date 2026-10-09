"""The OCR/layout text of an uploaded file, kept next to it (VRT-45): its
blocks with page and box, without the page images. What reads a
document after its run — a lens citing evidence — reads this instead of
parsing the file again."""

from __future__ import annotations

from idp.parsing.normalize import ParsedDocument
from idp.storage.object_store import ObjectStore


def parsed_key(storage_key: str) -> str:
    return f"{storage_key}.parsed.json"


def save_parsed(object_store: ObjectStore, storage_key: str, parsed: ParsedDocument) -> None:
    text_only = parsed.model_copy(update={"page_images_b64": {}})
    object_store.put(parsed_key(storage_key), text_only.model_dump_json().encode(), content_type="application/json")


def load_parsed(object_store: ObjectStore, storage_key: str) -> ParsedDocument | None:
    try:
        return ParsedDocument.model_validate_json(object_store.get(parsed_key(storage_key)))
    except Exception:
        return None  # not kept yet (a document processed before VRT-45)
