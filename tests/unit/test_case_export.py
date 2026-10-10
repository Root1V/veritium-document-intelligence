"""Unit tests for VRT-41: every export of a case result is derived from the
result contract — YAML and JSON are the contract itself, Markdown and PDF
name things as the catalogs do — and the API picks the format from Accept."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import yaml

from idp.api.case_contract import CaseInfo, CaseResultV1, ConditionResult, DocumentResult, Finding, ProfileRef, RunInfo, Verdict
from idp.api.routes.cases import _negotiate
from idp.domain.semantic_resolution import EvidenceSource, ResolvedAttribute
from idp.domain.verdict import VerdictReason
from idp.export.case_result import ExportLabels, render, to_markdown

NOW = datetime(2026, 10, 8, 22, 0, tzinfo=UTC)
PAYSLIP, INSURANCE = uuid.uuid4(), uuid.uuid4()
LABELS = ExportLabels(
    attributes={"persona.nombre_completo": "Nombre completo"},
    roles={"titular": "Titular"},
    document_types={"payslip": "Boleta de pago", "insurance_disclosure": "Declaración de seguro"},
)


def _result() -> CaseResultV1:
    def source(document_id, document_type, value):
        return EvidenceSource(document_id=document_id, document_type=document_type, field_path="name", value=value, page=0)

    name = ResolvedAttribute(
        role="titular",
        attribute="persona.nombre_completo",
        value=None,
        status="conflict",
        distinct_values=["SALAS SIGUAS, KATERIN", "PACHECO GOMEZ, KARIN"],
        sources=[source(PAYSLIP, "payslip", "SALAS SIGUAS, KATERIN"), source(INSURANCE, "insurance_disclosure", "PACHECO GOMEZ, KARIN")],
    )
    conflict = VerdictReason(kind="rule", decision="human_review", message="Nombre no coincide entre boleta y seguro.", ref={})
    return CaseResultV1(
        case=CaseInfo(
            id=uuid.uuid4(), external_ref="EXP-001", channel="online", status="completed",
            profile=ProfileRef(key="convenios", version=1, content_hash="x", semantic_catalog_version=3), created_at=NOW,
        ),
        verdict=Verdict(
            decision="return_to_client",
            reasons=[
                VerdictReason(kind="missing_document", decision="return_to_client", message="Falta: Carta de autorización", ref={}),
                conflict,
                conflict,
            ],
            decided_at=NOW,
        ),
        conditions=[
            ConditionResult(
                id=uuid.uuid4(), key="carta", label="Carta de autorización", kind="missing_document", document_type="authorization_letter",
                attributes=None, role=None, status="open", note=None, resolved_by_document_id=None, waived_by=None, waived_reason=None,
                opened_at=NOW, resolved_at=None,
            )
        ],
        semantic_catalog_version=3,
        entities={"titular": {"persona": {"nombre_completo": name}}},
        documents=[
            DocumentResult(id=PAYSLIP, filename="boleta.png", document_type="payslip", status="needs_review", needs_review=True,
                           parent_document_id=None, page_start=None, page_end=None, fields={"employee_name": {"value": "SALAS"}}),
            DocumentResult(id=INSURANCE, filename="seguro.png", document_type="insurance_disclosure", status="completed", needs_review=False,
                           parent_document_id=None, page_start=None, page_end=None, fields=None),
        ],
        findings=[
            Finding(id=uuid.uuid4(), rule_id="batch.employee_name_matches_insured_name", category="cross_document", severity="error", document_id=PAYSLIP,
                    field_path="employee_name", message="Nombre no coincide | entre boleta y seguro.", expected=None, actual=None,
                    confidence=1.0, confidence_method="deterministic", explanation="")
        ],
        run=RunInfo(run_number=3, trigger="correction", status="completed", started_at=NOW, finished_at=NOW, error=None,
                    scope={"kind": "attribute"}, provenance={"code_version": "abc123", "rules": [{"rule_id": "r1", "kind": "code", "version": "abc123"}]}),
    )


def test_json_and_yaml_are_the_contract_itself() -> None:
    result = _result()
    canonical = json.loads(result.model_dump_json())
    assert json.loads(render(result, "json", ExportLabels())) == canonical
    assert yaml.safe_load(render(result, "yaml", ExportLabels())) == canonical


def test_markdown_names_things_as_the_catalogs_do() -> None:
    md = to_markdown(_result(), LABELS)
    assert md.startswith("# Expediente EXP-001")
    assert "## Veredicto: Devolver al cliente" in md
    assert "Nombre no coincide entre boleta y seguro. (×2)" in md, "a reason repeated per document is shown once"
    assert "| Titular | Nombre completo | SALAS SIGUAS, KATERIN / PACHECO GOMEZ, KARIN | conflicto | Boleta de pago p.1, Declaración de seguro p.1 |" in md
    assert "| Carta de autorización | falta | — |" in md
    assert "Nombre no coincide \\| entre boleta" in md, "a pipe inside a cell does not break the table"
    assert "Corrida 3 (corrección, alcance attribute)" in md


def test_pdf_is_a_pdf_with_the_report() -> None:
    pypdfium2 = pytest.importorskip("pypdfium2")  # comes with the docling extra

    data = render(_result(), "pdf", LABELS)
    assert data.startswith(b"%PDF")
    document = pypdfium2.PdfDocument(data)
    text = "".join(page.get_textpage().get_text_range() for page in document)
    document.close()
    assert "Veredicto: Devolver al cliente" in text
    assert "Declaración de seguro" in text


def test_accept_picks_the_first_format_with_an_export() -> None:
    assert _negotiate(None) == "json"
    assert _negotiate("*/*") == "json"
    assert _negotiate("application/pdf") == "pdf"
    assert _negotiate("text/html, text/markdown;q=0.9, application/json;q=0.8") == "markdown"
    assert _negotiate("application/x-yaml") == "yaml"
