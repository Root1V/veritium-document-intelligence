"""Unit tests for VRT-33: the draft the model returns must be a valid type
definition (an invalid one is an error synaptum shows the model before
asking again), and only mappings the semantic catalog can accept survive."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from idp.classification.type_from_example import DraftMapping, TypeDraft, checked_mappings
from idp.domain.semantic_seed import seed_catalog


def _draft(**override) -> dict:
    return {
        "key": "electricity_bill", "display_name": "Recibo de luz", "description": "Recibo de servicio eléctrico",
        "extraction_hint": "El total está al pie.", "schema_title": "ElectricityBillSchema", "rationale": "x",
        "fields": [
            {"name": "holder_name", "type": "str", "required": True, "description": "Titular del suministro"},
            {"name": "holder_dni", "type": "str", "required": False, "description": "DNI del titular"},
            {"name": "lines", "type": "list", "required": False, "description": "Detalle", "item_name": "BillLine",
             "items": [{"name": "amount", "type": "float", "required": True, "description": "Importe"}]},
        ],
    } | override


def test_a_valid_draft_is_a_type_definition():
    definition = TypeDraft.model_validate(_draft()).definition()
    assert definition.key == "electricity_bill" and definition.field_paths() == {"holder_name", "holder_dni", "lines[].amount"}


def test_an_invalid_draft_is_rejected_with_the_reason():
    bad = _draft(fields=[{"name": "lines", "type": "list", "required": False, "description": "Detalle"}])
    with pytest.raises(ValidationError, match="items"):
        TypeDraft.model_validate(bad)


def test_only_mappings_the_catalog_accepts_survive():
    definition = TypeDraft.model_validate(_draft()).definition()
    kept, dropped = checked_mappings(
        definition,
        [
            DraftMapping(field_path="holder_dni", attribute="persona.dni", role="titular"),
            DraftMapping(field_path="holder_name", attribute="persona.apodo", role="titular"),
            DraftMapping(field_path="holder_name", attribute="persona.nombre_completo", role="vecino"),
            DraftMapping(field_path="missing", attribute="persona.dni", role="titular"),
        ],
        seed_catalog(),
    )
    assert [m.field_path for m in kept] == ["holder_dni"]
    assert len(dropped) == 3 and any("persona.apodo" in d for d in dropped) and any("vecino" in d for d in dropped)
