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
