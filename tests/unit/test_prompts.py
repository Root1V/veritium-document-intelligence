"""Unit tests for VRT-46: a prompt's version follows its text, the template
synaptum receives renders to exactly the prompt, and a field's business
meaning comes from the semantic catalog."""

from __future__ import annotations

import pytest

from idp.domain.semantic import field_meanings
from idp.domain.semantic_seed import seed_catalog
from idp.llm.prompts import Prompt, prompt, versions


def test_the_version_follows_the_text() -> None:
    assert Prompt("x", "uno").version == Prompt("x", "uno").version
    assert Prompt("x", "uno").version != Prompt("x", "uno.").version


def test_synaptum_renders_the_template_back_to_the_exact_prompt() -> None:
    template = Prompt("x", 'Tipos: {types}. Formato: {{"a": 1}}').render(types="boleta")
    assert template.render() == 'Tipos: boleta. Formato: {"a": 1}'
    assert (template.name, template.version) == ("x", Prompt("x", 'Tipos: {types}. Formato: {{"a": 1}}').version)


def test_a_name_cannot_point_to_two_texts() -> None:
    from idp.llm import prompts as registry

    prompt("test_only", "a")
    try:
        with pytest.raises(ValueError):
            prompt("test_only", "b")
    finally:
        registry._REGISTRY.pop("test_only")


def test_every_prompt_of_the_platform_is_versioned() -> None:
    assert {"classify", "segment", "extract_agentic", "extract_generic", "entity_judge", "draft_rule", "lens_summary", "lens_playbook"} <= set(versions())


def test_a_field_means_what_its_attribute_says() -> None:
    meanings = field_meanings(seed_catalog(), "payslip")
    assert meanings["employee_code"].startswith("Código de empleado del titular: Código del trabajador")
    assert "period" not in meanings, "an unmapped field has no business meaning to add"


def test_the_text_in_effect_is_a_trial_then_the_published_then_the_code() -> None:
    from idp.llm.prompts import set_published, trial

    p = prompt("test_effect", "codigo {x}", filled=("x",))
    try:
        assert p.effective == "codigo {x}" and p.version == p.code_version
        set_published({"test_effect": "publicado {x}"})
        assert p.effective == "publicado {x}" and p.render(x="1").render() == "publicado 1"
        with trial({"test_effect": "borrador {x}"}):
            assert p.effective == "borrador {x}"
        assert p.effective == "publicado {x}", "a trial ends with its context"
    finally:
        set_published({})
        from idp.llm import prompts as registry

        registry._REGISTRY.pop("test_effect")


def test_a_draft_keeps_the_values_the_platform_fills_in() -> None:
    from idp.llm.prompts import Prompt, draft_problems

    p = Prompt("t", "Tipos: {types}. Responde en JSON {{...}}.", filled=("types",))
    assert draft_problems(p, "Tipos: {types}. Breve.") == []
    assert draft_problems(p, "Sin tipos.") == ["falta {types}, que la plataforma completa en cada uso"]
    assert draft_problems(p, "Tipos: {types} {otro}") == ["{otro} no es un dato que la plataforma complete aquí"]
    assert "llaves mal cerradas" in draft_problems(p, "Tipos: {types} {")[0]
    assert draft_problems(Prompt("t", "Sin variables {literal}"), "Otro texto con {llaves}") == [], "never filled in: braces are literal"


def test_a_prompt_declares_exactly_the_values_its_text_uses() -> None:
    with pytest.raises(ValueError, match="declara"):
        prompt("test_mismatch", "Hola {a}", filled=("b",))
