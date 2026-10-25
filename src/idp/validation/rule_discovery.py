"""Drafts a CEL-backed validation rule from a human's plain-language
description (VRT-03, extended in VRT-36). A rule targets either a document
type's fields or a semantic attribute — then it runs on every document that
contributes the attribute, whatever its type. The draft says AMBIGUA instead
of guessing when the description is missing something, and comes with test
cases that must pass before a human can activate it
(api/routes/validation_rules.py). This module never persists anything or
makes a rule live."""

from __future__ import annotations

from idp.config import Settings
from idp.domain.rule_draft import RuleDraft
from idp.domain.semantic import SemanticCatalog
from idp.llm.port import model_for, structured
from idp.llm.prompts import prompt
from idp.observability.otel import traced_llm_call

_SYSTEM_PROMPT = prompt("draft_rule", """You are an agent that translates a natural-language description of a business validation rule \
into a safe, deterministic CEL (Common Expression Language) expression, with test cases.

Variables available in CEL:
- value: the attribute's value, ONLY if the rule is about a semantic attribute (e.g. ingreso.neto_mensual).
- doc.<field>: fields of the current document (rules about a document type).
- case.<role>.<entity>.<attribute>: the consolidated view of the case (e.g. case.titular.persona.dni), to compare \
with other data of the case.
- request.<field>: process data sent by the caller.
- ONLY if the category is "reference_data": reference_data.employee_code_exists (precomputed boolean).

Operators: ==, !=, <, <=, >, >=, &&, ||, !, ?:. has(x.field) before using a field that may be missing. \
Strings: .matches(regex), .startsWith, .endsWith, .contains, size(). Lists: .all, .exists, .filter. \
No loops, network or database: CEL is not Turing-complete and has no side effects. CEL does not compare integers \
with decimals: amounts are written as decimals, in the condition and in the cases (1025.0, not 1025).

AMBIGUOUS: if the description is not enough to write the condition without inventing something — a threshold \
without a number ("ingreso suficiente"), a definition that is not given ("cliente válido"), data from another \
system — do NOT write CEL: answer outcome="ambiguous" with the concrete questions that would resolve it, written \
in Spanish. Inventing a threshold is worse than asking.

The description is in Spanish. If it can be done (outcome="ok"), generate:
1. condition_cel: the condition that must HOLD (if it is false, the rule fails).
2. applies_when_cel, optional (no reference_data.), or null.
3. severity: "error" blocks, "warning" for review, "info" only informs.
4. message_pass / message_fail: brief, in Spanish.
5. rationale: the logic in 1-2 sentences in Spanish, so a person can check it without reading CEL.
6. test_cases: at least one case that holds (expect "pass") and one that does not (expect "fail"), with realistic \
values in input (value, doc, case or request depending on what the condition uses); each name in Spanish.""")


def draft_rule(
    settings: Settings,
    *,
    description: str,
    document_type: str | None,
    attribute: str | None,
    category: str,
    field_path: str | None,
    existing_fields_hint: list[str] | None = None,
    semantic: SemanticCatalog | None = None,
) -> RuleDraft:
    if attribute is not None:
        definition = next((a for a in semantic.attributes if a.key == attribute), None) if semantic else None
        target = f"Rule about the semantic attribute {attribute}" + (
            f" ({definition.data_type}): {definition.definition} The condition uses `value`." if definition else "."
        )
    else:
        target = f"Rule about the document type: {document_type}"
        if existing_fields_hint:
            target += f"\nKnown fields of {document_type}: {', '.join(existing_fields_hint)}."
    field_hint = f"\nMain related field: {field_path}." if field_path else ""
    case_hint = (
        "\nCase attributes available as case.<role>.<attribute>: " + ", ".join(a.key for a in semantic.attributes)
        if semantic is not None
        else ""
    )
    user_message = f"{target}\nCategory: {category}\nRule description: {description}{field_hint}{case_hint}"
    with traced_llm_call(role="reasoning", model=model_for("reasoning")):
        return structured(
            purpose="draft_rule",
            role="reasoning",
            output=RuleDraft,
            instructions=_SYSTEM_PROMPT.render(),
            task=user_message,
        )
