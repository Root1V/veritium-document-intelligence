"""VRT-118: signed and sealed documents. The seal comes from the layout, the
signature from the vision model only when a process asks for it; a document
there without them is the client's to redo, an unchecked signature a person's
to look at. No DB, no LLM (the vision model is faked)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from idp.domain import attestation
from idp.domain.attestation import Attestations, attest, seals, signature_pages
from idp.domain.completeness import CaseDocument, evaluate_checklist
from idp.domain.process_profile import ChecklistItem, ProcessProfileDefinition
from idp.domain.verdict import OpenCondition, VerdictInputs, decide
from idp.parsing.normalize import ParsedBlock, ParsedDocument


def _parsed(*blocks: tuple[int, str, str]) -> ParsedDocument:
    return ParsedDocument(
        backend="t", page_count=3, page_images_b64={0: "p0", 1: "p1", 2: "p2"},
        blocks=[ParsedBlock(region_id=i, text=text, page=page, bbox=[0, 0, 1, 1], confidence=0.9, block_type=kind) for i, (page, kind, text) in enumerate(blocks)],
    )


def test_a_seal_is_what_the_layout_labels_one():
    assert seals(_parsed((0, "text", "CARTA"), (2, "seal", ""))) == [2]


def test_the_signature_is_looked_for_where_the_document_asks_for_it():
    assert signature_pages(_parsed((0, "text", "CARTA"), (1, "text", "Firma del cliente"))) == [1]
    assert signature_pages(_parsed((0, "text", "CARTA"))) == [2], "else the last page"


class _Vision:
    def __init__(self, answers: dict[str, str] | Exception):
        self.answers, self.pages = answers, []

    async def vision(self, *, purpose: str, image_b64: str, prompt: str) -> str:
        self.pages.append(image_b64)
        if isinstance(self.answers, Exception):
            raise self.answers
        return self.answers[image_b64]


@pytest.fixture
def vision(monkeypatch):
    def use(answers):
        fake = _Vision(answers)
        monkeypatch.setattr("idp.llm.port.inference", lambda: fake)
        return fake
    return use


def test_the_vision_model_is_asked_only_when_a_process_wants_it(vision):
    fake = vision({"p1": "SIGNED, bottom right"})
    parsed = _parsed((1, "text", "Firma"), (2, "seal", ""))
    assert asyncio.run(attest(parsed, check_signature=False)) == Attestations(sealed_pages=[2])
    assert fake.pages == []
    assert asyncio.run(attest(parsed, check_signature=True)) == Attestations(sealed_pages=[2], signed=True, signed_pages=[1])


def test_an_unanswered_check_is_not_an_unsigned_document(vision):
    vision(RuntimeError("timeout"))
    assert asyncio.run(attest(_parsed((1, "text", "Firma")), check_signature=True)).signed is None


LETTER = ChecklistItem(key="carta", label="Carta de autorización", document_type="authorization_letter", must_be_signed=True, must_be_sealed=True)


def _kind(**attest_fields) -> str | None:
    doc = CaseDocument(document_id=uuid.uuid4(), document_type="authorization_letter", status="extracted",
                       attestations=Attestations(**attest_fields) if attest_fields else None)
    [outcome] = evaluate_checklist(ProcessProfileDefinition(name="p", semantic_catalog_version=1, checklist=[LETTER]), [doc], None, {})
    return None if outcome.satisfied else outcome.condition_kind


def test_a_document_without_its_signature_or_seal():
    assert _kind(sealed_pages=[0], signed=True) is None
    assert _kind(sealed_pages=[], signed=True) == "unsealed_document"
    assert _kind(sealed_pages=[0], signed=False) == "unsigned_document"
    assert _kind(sealed_pages=[0], signed=None) == "unchecked_signature"
    assert _kind() == "unsealed_document", "extracted before VRT-118: no seal found"


def test_the_client_signs_and_a_person_checks():
    verdict = decide(VerdictInputs(open_conditions=[
        OpenCondition(key="a", label="Carta", kind="unsigned_document"), OpenCondition(key="b", label="Seguro", kind="unchecked_signature"),
    ]), None)
    assert [(r.decision, r.message) for r in verdict.reasons] == [("return_to_client", "Sin firma: Carta"), ("human_review", "Comprobar la firma: Seguro")]


def test_a_signature_is_asked_of_a_document_not_of_a_data_item():
    with pytest.raises(ValueError, match="firma y sello"):
        ChecklistItem(key="i", label="Ingreso", requires_attributes=["ingreso.neto_mensual"], must_be_signed=True)


def test_the_prompt_is_registered():
    assert "SIGNED" in str(attestation._LOOK)
