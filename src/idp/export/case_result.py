"""Exports of a case result (VRT-41): JSON, YAML, Markdown and PDF, all
derived from the canonical result contract (api/case_contract.py) and never
from the database, so every format says the same thing. JSON and YAML are
the contract itself. Markdown and PDF are for people: one report built from
the contract, naming attributes, roles and document types as the catalogs
do (ExportLabels) instead of by key, and drawn in each format."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import yaml
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pydantic import BaseModel

from idp.api.case_contract import CaseResultV1

ExportFormat = Literal["json", "yaml", "markdown", "pdf"]

MEDIA_TYPES: dict[ExportFormat, str] = {
    "json": "application/json",
    "yaml": "application/yaml",
    "markdown": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
}
EXTENSIONS: dict[ExportFormat, str] = {"json": "json", "yaml": "yaml", "markdown": "md", "pdf": "pdf"}

_DECISION = {"continue": "Continuar", "human_review": "Revisión humana", "return_to_client": "Devolver al cliente"}
_CONDITION = {"open": "falta", "resolved": "cumplida", "waived": "dispensada"}
_ATTRIBUTE = {"consistent": "coincide", "conflict": "conflicto", "single_source": "una fuente"}
_SEVERITY = {"error": "error", "warning": "advertencia", "info": "info"}
_TRIGGER = {"submit": "envío", "documents_added": "documentos agregados", "reprocess": "reproceso", "correction": "corrección"}


class ExportLabels(BaseModel):
    """Display names from the catalogs the case was resolved against."""

    attributes: dict[str, str] = {}
    roles: dict[str, str] = {}
    document_types: dict[str, str] = {}


@dataclass
class _Block:
    kind: Literal["h1", "h2", "p", "bullets", "table"]
    text: str = ""
    items: list[str] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


def _show(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return json.dumps(value, ensure_ascii=False) if isinstance(value, dict | list) else str(value)


def _report(result: CaseResultV1, labels: ExportLabels) -> list[_Block]:
    documents = {d.id: d for d in result.documents}

    def type_name(key: str | None) -> str:
        return labels.document_types.get(key, key) if key else "Sin clasificar"

    def document_name(document_id: Any) -> str:
        d = documents.get(document_id)
        return f"{type_name(d.document_type)} ({d.filename})" if d else "—"

    case = result.case
    profile = f"perfil {case.profile.key} v{case.profile.version}" if case.profile else "sin perfil"
    catalog = f"catálogo semántico v{result.semantic_catalog_version}" if result.semantic_catalog_version else "sin catálogo semántico"
    blocks = [
        _Block("h1", f"Expediente {case.external_ref or case.id}"),
        _Block("p", f"{profile} · {catalog} · canal {case.channel} · estado {case.status} · generado {datetime.now(UTC):%Y-%m-%d %H:%M} UTC"),
    ]

    decision = _DECISION.get(result.verdict.decision or "", "pendiente")
    # A cross-document finding is reported once per document involved: shown once with a count.
    reasons = Counter((_DECISION[r.decision], r.message) for r in result.verdict.reasons)
    blocks.append(_Block("h2", f"Veredicto: {decision}"))
    blocks.append(
        _Block("bullets", items=[f"[{d}] {m}" + (f" (×{n})" if n > 1 else "") for (d, m), n in reasons.items()] or ["Sin observaciones."])
    )

    if result.conditions:
        blocks.append(_Block("h2", "Requisitos del perfil"))
        blocks.append(
            _Block(
                "table",
                headers=["Requisito", "Estado", "Detalle"],
                rows=[
                    [
                        c.label,
                        _CONDITION[c.status],
                        f"dispensada por {c.waived_by}: {c.waived_reason}" if c.status == "waived" else (c.note or "—"),
                    ]
                    for c in result.conditions
                ],
            )
        )

    rows = []
    for role, entities in result.entities.items():
        for attributes in entities.values():
            for a in attributes.values():
                sources = ", ".join(
                    f"{type_name(s.document_type)}" + (f" p.{s.page + 1}" if s.page is not None else "") for s in a.sources
                )
                value = _show(a.value) if a.status != "conflict" else " / ".join(_show(v) for v in a.distinct_values)
                rows.append([labels.roles.get(role, role), labels.attributes.get(a.attribute, a.attribute), value, _ATTRIBUTE[a.status], sources])
    blocks.append(_Block("h2", "Lo que dice el expediente"))
    blocks.append(
        _Block("table", headers=["Rol", "Atributo", "Valor", "Estado", "Fuentes"], rows=rows)
        if rows
        else _Block("p", "Sin atributos del catálogo semántico en este expediente.")
    )

    if result.findings:
        blocks.append(_Block("h2", f"Hallazgos ({len(result.findings)})"))
        blocks.append(
            _Block(
                "table",
                headers=["Severidad", "Regla", "Mensaje", "Documento"],
                rows=[[_SEVERITY.get(f.severity, f.severity), f.rule_id, f.message, document_name(f.document_id)] for f in result.findings],
            )
        )

    blocks.append(_Block("h2", f"Documentos ({len(result.documents)})"))
    blocks.append(
        _Block(
            "table",
            headers=["Tipo", "Archivo", "Estado", "Revisión"],
            rows=[[type_name(d.document_type), d.filename, d.status, "pendiente" if d.needs_review else "—"] for d in result.documents],
        )
    )

    blocks.append(_Block("h2", "Procedencia"))
    run = result.run
    if run is None:
        blocks.append(_Block("p", "El expediente aún no tiene una corrida."))
    else:
        provenance = run.provenance or {}
        scope = f", alcance {run.scope['kind']}" if run.scope else ""
        items = [
            f"Corrida {run.run_number} ({_TRIGGER.get(run.trigger, run.trigger)}{scope}): {run.status}, "
            f"{run.started_at:%Y-%m-%d %H:%M} → {run.finished_at:%Y-%m-%d %H:%M} UTC"
            if run.started_at and run.finished_at
            else f"Corrida {run.run_number} ({_TRIGGER.get(run.trigger, run.trigger)}{scope}): {run.status}",
            f"Contrato de resultado v{result.contract_version} · código {provenance.get('code_version', '—')}",
        ]
        if models := provenance.get("models"):
            items.append("Modelos: " + ", ".join(f"{role} {model}" for role, model in models.items()))
        if rules := provenance.get("rules"):
            items.append("Reglas evaluadas: " + ", ".join(f"{r['rule_id']} ({r['version']})" for r in rules))
        if run.error:
            items.append(f"Observación de la corrida: {run.error}")
        blocks.append(_Block("bullets", items=items))
    return blocks


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(result: CaseResultV1, labels: ExportLabels) -> str:
    lines: list[str] = []
    for b in _report(result, labels):
        if b.kind == "h1":
            lines += [f"# {b.text}", ""]
        elif b.kind == "h2":
            lines += [f"## {b.text}", ""]
        elif b.kind == "p":
            lines += [b.text, ""]
        elif b.kind == "bullets":
            lines += [f"- {item}" for item in b.items] + [""]
        else:
            lines.append("| " + " | ".join(b.headers) + " |")
            lines.append("|" + "---|" * len(b.headers))
            lines += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in b.rows]
            lines.append("")
    return "\n".join(lines)


# The PDF's built-in fonts are Latin-1: Spanish fits; a few typographic
# characters are swapped for their nearest Latin-1 form.
_LATIN1 = str.maketrans({"—": "-", "–": "-", "→": "->", "“": '"', "”": '"', "‘": "'", "’": "'", "…": "..."})


def _pdf_text(text: str) -> str:
    return text.translate(_LATIN1).encode("latin-1", "replace").decode("latin-1")


def to_pdf(result: CaseResultV1, labels: ExportLabels) -> bytes:
    pdf = FPDF(orientation="landscape", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    for b in _report(result, labels):
        if b.kind in ("h1", "h2"):
            if b.kind == "h2" and pdf.get_y() > pdf.h - 40:
                pdf.add_page()  # a heading does not stay alone at the foot of a page
            pdf.ln(2 if b.kind == "h2" else 0)
            pdf.set_font("Helvetica", "B", 16 if b.kind == "h1" else 12)
            pdf.multi_cell(0, 8, _pdf_text(b.text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        elif b.kind == "p":
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, _pdf_text(b.text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        elif b.kind == "bullets":
            pdf.set_font("Helvetica", "", 9)
            for item in b.items:
                pdf.multi_cell(0, 5, _pdf_text(f"- {item}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            pdf.set_font("Helvetica", "", 8)
            # Columns as wide as their longest text, within bounds.
            widths = [min(max(len(row[i]) for row in [b.headers, *b.rows]), 60) + 4 for i in range(len(b.headers))]
            with pdf.table(col_widths=widths, text_align="LEFT", line_height=5, first_row_as_headings=True) as table:
                for row in [b.headers, *b.rows]:
                    cells = table.row()
                    for cell in row:
                        cells.cell(_pdf_text(cell))
        pdf.ln(1)
    return bytes(pdf.output())


def render(result: CaseResultV1, fmt: ExportFormat, labels: ExportLabels) -> bytes:
    if fmt == "json":
        return result.model_dump_json(indent=2).encode()
    if fmt == "yaml":
        return yaml.safe_dump(result.model_dump(mode="json"), allow_unicode=True, sort_keys=False).encode()
    if fmt == "markdown":
        return to_markdown(result, labels).encode()
    return to_pdf(result, labels)
