"""VRT-116: the line with «<» of ID cards and passports, checked by its ICAO
9303 digits and against what was extracted. No DB, no LLM. The lines are the
ICAO specimen and an invented card, never a person's."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from idp.domain.machine_readable_zone import find_zones, parse_line
from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.validation.context import DocumentFields, ValidationContext
from idp.validation.rules.self_rules import MachineReadableZoneChecks

CARD = "0001234565ARG8503149F3001019<<<<<<<0"  # TD2, invented: N° 000123456, born 1985-03-14
PASSPORT = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"  # TD3, the ICAO 9303 specimen


def test_the_check_digits_of_a_card_and_a_passport():
    card, passport = parse_line(CARD), parse_line(PASSPORT)
    assert (card.number, card.birth, card.failed) == ("000123456", "850314", [])
    assert (passport.number, passport.birth, passport.expiry, passport.failed) == ("L898902C3", "740812", "120415", [])


def test_a_misread_digit_breaks_its_check():
    assert parse_line(CARD.replace("8503149", "8508149")).failed == ["birth", "composite"]


def test_only_data_lines_are_zones():
    parsed = ParsedDocument(backend="t", page_count=1, blocks=[
        ParsedBlock(region_id=0, text="C<ARGPEREZ<<ANA<MARIA<<<<<<<<<<<<<<", page=0, bbox=[0, 0, 1, 1], confidence=0.9),
        ParsedBlock(region_id=1, text=CARD[:18] + " " + CARD[18:], page=1, bbox=[0, 0, 1, 1], confidence=0.9),
    ])
    assert [(z.page, z.number) for z in find_zones(parsed)] == [(1, "000123456")]


def _check(person: dict, line: str = CARD):
    payload = {"persons": [{k: {"value": v} for k, v in person.items()}], "machine_readable_zones": [parse_line(line, 1).model_dump()]}
    doc = DocumentFields(document_id=uuid.uuid4(), document_type="foreign_resident_id", fields={}, payload=payload)
    context = ValidationContext(case_id=uuid.uuid4(), current_document=doc, sibling_documents=[], request_payload=None, reference_data=None, external_system=None)
    rule = MachineReadableZoneChecks()
    assert rule.applies_when(context)
    return asyncio.run(rule.evaluate(context))


@pytest.mark.parametrize("birth", ["14 Mar 1985", "14/03/1985", "1985-03-14"])
def test_it_passes_when_the_line_says_what_was_extracted(birth):
    assert _check({"foreigner_id_number": "N° 000123456", "date_of_birth": birth}).passed


def test_a_birth_date_that_is_not_the_lines_goes_to_review():
    result = _check({"foreigner_id_number": "000123456", "date_of_birth": "14 Mar 1958"})
    assert (result.passed, result.severity, result.field_path) == (False, "warning", "persons[0].date_of_birth")
    assert "pág. 2" in result.message


def test_a_line_whose_digits_do_not_match_goes_to_review():
    result = _check({"foreigner_id_number": "000123456", "date_of_birth": "14 Mar 1985"}, CARD[:-1] + "1")
    assert (result.passed, result.field_path) == (False, "persons[0].foreigner_id_number")
    assert "dígitos de control" in result.message


def test_a_number_no_one_has():
    result = _check({"foreigner_id_number": "000999999", "date_of_birth": "14 Mar 1985"})
    assert not result.passed and result.field_path is None
