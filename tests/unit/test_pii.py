"""Masking of a case's personal data (VRT-58): each datum by its semantic
class, and the same data wherever a response quotes them."""

from __future__ import annotations

from idp.domain.pii import HIDDEN, Masker, mask_value
from idp.domain.semantic_seed import seed_catalog


def _env(value, text=None):
    return {"value": value, "confidence": 0.9, "source_text": text if text is not None else str(value)}


PAYSLIP = {
    "employee_name": _env("SALAS SIGUAS KATERIN KAROLA"),
    "employee_code": _env("70349965"),
    "employer_name": _env("MUNICIPALIDAD DE LIMA"),
    "net_pay": _env(2500.0, "S/ 2,500.00"),
    "period": _env("2024-05"),
}
LETTER = {"client_dni": _env("42285866"), "client_name": _env("Katerin Salas")}


def test_each_datum_is_masked_by_its_class():
    assert mask_value("42285866", "personal") == "••••5866"
    assert mask_value("Katerin Karola Salas", "personal") == "K. K. S."
    assert mask_value("1990-05-12", "personal") == HIDDEN
    assert mask_value(2500.0, "sensitive") == HIDDEN
    assert mask_value("MUNICIPALIDAD DE LIMA", "none") == "MUNICIPALIDAD DE LIMA"


def test_a_case_response_is_masked_wherever_it_quotes_a_datum():
    masker = Masker.for_documents(seed_catalog(), [("payslip", PAYSLIP), ("authorization_letter", LETTER)], extra=["PE"])
    result = masker.json({
        "fields": PAYSLIP,
        "message": "El DNI del titular no coincide: 42285866 (Carta) frente a 42785091 (Seguro)",
        "reason": "Katerin Salas no figura en la planilla; neto S/ 2,500.00",
        "run_number": 1, "confidence": 0.9, "case_id": "42285866-0000-0000-0000-000000000000",
    })
    fields = result["fields"]
    assert fields["employee_name"]["value"] == "S. S. K. K." and "KATERIN" not in fields["employee_name"]["source_text"]
    assert fields["net_pay"]["value"] == HIDDEN and "2,500" not in fields["net_pay"]["source_text"]
    assert fields["employer_name"]["value"] == "MUNICIPALIDAD DE LIMA", "the employer's name is not a person's"
    assert fields["period"]["value"] == HIDDEN, "an unmapped field counts as personal"
    assert "42285866" not in result["message"] and "••••5866" in result["message"]
    assert "42785091" in result["message"], "a value of no case document is not known to be personal"
    assert "Katerin" not in result["reason"] and "2,500" not in result["reason"]
    assert result["run_number"] == 1 and result["confidence"] == 0.9
    assert result["case_id"] == "42285866-0000-0000-0000-000000000000", "only whole words: an id is not a DNI"


def test_a_list_item_takes_its_class_from_the_mapping_of_any_index():
    card = {"persons": [{"foreigner_id_number": _env("001234567"), "nationality": _env("VENEZOLANA")},
                        {"foreigner_id_number": _env("009876543"), "nationality": _env("COLOMBIANA")}]}
    masked = Masker.for_documents(seed_catalog(), [("foreign_resident_id", card)]).json(card)
    assert [p["foreigner_id_number"]["value"] for p in masked["persons"]] == ["••••4567", "••••6543"]


def test_seeing_the_data_masks_nothing():
    data = {"fields": PAYSLIP}
    assert Masker.clear().json(data) == data
