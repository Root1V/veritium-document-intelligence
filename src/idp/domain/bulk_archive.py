"""How a bulk archive becomes cases (VRT-48), the pure part. The archive is
a ZIP with one folder per case: the folder's name is the case's reference
and its files are the case's documents. Optionally a table at the root
(``manifiesto.csv`` / ``.xlsx``) gives one row per case: ``expediente``
(the folder), ``perfil`` (else the job's default) and any other column as
the case's process data. What cannot become a case is skipped with a
reason a person can act on; the rest goes ahead."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

DOCUMENT_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp")
MANIFEST_NAMES = ("manifiesto.csv", "manifiesto.xlsx", "manifest.csv", "manifest.xlsx")
REFERENCE, PROFILE = "expediente", "perfil"


class PlannedCase(BaseModel):
    reference: str
    profile: str
    process_data: dict[str, Any]
    files: list[str]  # paths inside the archive


class Skipped(BaseModel):
    reference: str | None
    reason: str


def _ignored(path: str) -> bool:
    return path.startswith("__MACOSX/") or any(part.startswith(".") for part in path.split("/"))


def manifest_path(paths: list[str]) -> str | None:
    """The manifest at the archive's root, or inside its single top folder."""
    for path in paths:
        parts = path.split("/")
        if parts[-1].lower() in MANIFEST_NAMES and len(parts) <= 2 and not _ignored(path):
            return path
    return None


def _cell(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # Excel reads 30 as 30.0
    return "" if value is None else str(value).strip()


def plan(
    files: list[tuple[str, int]],
    manifest_rows: list[dict[str, Any]] | None,
    *,
    default_profile: str | None,
    max_cases: int,
    max_file_bytes: int,
) -> tuple[list[PlannedCase], list[Skipped]]:
    """``files``: (path, size) of every file in the archive. Raises
    ValueError when the archive as a whole cannot be used."""
    paths = [p for p, _ in files if not _ignored(p) and not p.endswith("/")]
    manifest = manifest_path(paths)
    usable = set(paths) - {manifest}
    documents = [(p, size) for p, size in files if p in usable]
    # A ZIP made by compressing one folder puts everything under it: skip that level.
    tops = {p.split("/")[0] for p, _ in documents}
    if len(tops) == 1 and all(p.count("/") >= 2 for p, _ in documents):
        prefix = next(iter(tops)) + "/"
        documents = [(p.removeprefix(prefix), size) for p, size in documents]
        root = prefix
    else:
        root = ""

    skipped: list[Skipped] = []
    folders: dict[str, list[str]] = {}
    for path, size in documents:
        if "/" not in path:
            skipped.append(Skipped(reference=None, reason=f"{path}: está fuera de una carpeta; cada expediente va en su propia carpeta."))
            continue
        reference, name = path.split("/", 1)[0], path.rsplit("/", 1)[-1]
        if not name.lower().endswith(DOCUMENT_EXTENSIONS):
            skipped.append(Skipped(reference=reference, reason=f"{name}: formato no admitido (se aceptan PDF e imágenes)."))
            continue
        if size > max_file_bytes:
            skipped.append(Skipped(reference=reference, reason=f"{name}: pesa más de {max_file_bytes // (1024 * 1024)} MB."))
            continue
        folders.setdefault(reference, []).append(root + path)

    rows: dict[str, dict[str, Any]] = {}
    for raw in manifest_rows or []:
        row = {str(k).strip().lower(): _cell(v) for k, v in raw.items() if k is not None}
        if REFERENCE not in row:
            raise ValueError(f"el manifiesto debe tener la columna '{REFERENCE}'")
        if row[REFERENCE]:
            rows[row[REFERENCE]] = row
    for reference in rows.keys() - folders.keys():
        skipped.append(Skipped(reference=reference, reason="está en el manifiesto pero no hay una carpeta con ese nombre (o no tiene documentos válidos)."))

    if len(folders) > max_cases:
        raise ValueError(f"el archivo trae {len(folders)} expedientes; el máximo por carga es {max_cases}")
    planned: list[PlannedCase] = []
    for reference in sorted(folders):
        row = rows.get(reference, {})
        profile = row.get(PROFILE) or default_profile
        if not profile:
            skipped.append(Skipped(reference=reference, reason="no tiene perfil de proceso: indícalo en el manifiesto o elige uno por defecto."))
            continue
        data = {k: v for k, v in row.items() if k not in (REFERENCE, PROFILE) and v != ""}
        planned.append(PlannedCase(reference=reference, profile=profile, process_data=data, files=sorted(folders[reference])))
    return planned, skipped
