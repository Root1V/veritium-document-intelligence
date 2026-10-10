"""The discrepancy investigator (VRT-66), its pure parts: what is kept of
the agent's answer, and its deterministic tools over a case's documents."""

from __future__ import annotations

import uuid

import pytest

from idp.config import Settings
from idp.domain.lenses import LensDocument
from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.persistence.models import Case
from idp.pipeline.investigation import Cited, InvestigationAnswer, finalize, investigator_tools

BOLETA = LensDocument(
    document_id=uuid.uuid4(),
    document_type="payslip",
    name="Boleta de pago (boleta.pdf)",
    parsed=ParsedDocument(
        backend="test",
        page_count=1,
        blocks=[
            ParsedBlock(region_id=0, text="Apellidos y Nombres : PEREZ ROJAS, ANA", page=0, bbox=[0, 0, 1, 0.1], confidence=0.9),
            ParsedBlock(region_id=1, text="Codigo: 0012345", page=0, bbox=[0, 0.1, 1, 0.2], confidence=0.9),
        ],
    ),
)
FIELDS = {BOLETA.document_id: {"employee_name": "PEREZ ROJAS ANA", "employee_code": "0012845"}}


def _answer(**kw) -> InvestigationAnswer:
    base = {"diagnosis": "El código se leyó mal.", "cause": "error_de_lectura", "action": "corregir_dato", "document": "d1", "field": "employee_code",
            "value": "0012345", "confidence": 0.8, "evidence": [Cited(document="d1", page=1, text="Codigo: 0012345")]}
    return InvestigationAnswer.model_validate(base | kw)


def test_a_correction_is_kept_with_its_document_and_verified_evidence():
    kept = finalize(_answer(), [BOLETA], FIELDS)
    assert kept["action"] == "corregir_dato" and kept["document_id"] == BOLETA.document_id and kept["suggested_value"] == "0012345"
    assert kept["evidence"][0]["verified"] is True and kept["evidence"][0]["document"] == "Boleta de pago (boleta.pdf)"


def test_evidence_that_is_not_in_the_document_is_marked_unverified():
    kept = finalize(_answer(evidence=[Cited(document="d1", text="Codigo: 9999999")]), [BOLETA], FIELDS)
    assert kept["evidence"][0]["verified"] is False


@pytest.mark.parametrize(
    "bad", [{"field": "no_existe"}, {"document": "d7"}, {"value": ""}, {"value": None}],
)
def test_a_correction_that_does_not_point_at_an_extracted_datum_becomes_a_manual_review(bad):
    kept = finalize(_answer(**bad), [BOLETA], FIELDS)
    assert kept["action"] == "revisar_manualmente" and kept["document_id"] is None and kept["suggested_value"] is None
    assert "revisión manual" in kept["diagnosis"]


def test_other_actions_carry_no_value():
    kept = finalize(_answer(action="pedir_documento", cause="documentos_de_otra_persona", document=None, field=None), [BOLETA], FIELDS)
    assert kept["action"] == "pedir_documento" and kept["suggested_value"] is None


@pytest.mark.asyncio
async def test_reading_searching_and_comparing_need_no_model():
    tools = {t.name: t for t in investigator_tools(Settings(_env_file=None), Case(id=uuid.uuid4()), [BOLETA])}
    def text(result) -> str:
        return " ".join(p.text for p in result.content)

    read = await tools["read_document"].invoke("c1", {"document": "d1", "page": 1})
    assert "[r1 pág.1] Codigo: 0012345" in text(read)
    found = await tools["search_document"].invoke("c2", {"document": "d1", "text": "perez rojas"})
    assert text(found).startswith("[r0 pág.1]")
    names = await tools["compare_names"].invoke("c3", {"name_a": "ANA PEREZ ROJAS", "name_b": "PEREZ ROJAS, ANA"})
    assert "la misma persona" in text(names)
    unknown = await tools["read_document"].invoke("c4", {"document": "d9"})
    assert unknown.is_error and "d1" in text(unknown), "a wrong reference comes back to the agent as an error it can fix"
