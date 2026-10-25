"""Value object for the rule-discovery step: the LLM's structured draft of
a CEL condition + human-facing messages from a plain-language description.
A human still reviews/edits/activates it
(api/routes/validation_rules.py) — this module only drafts it, mirroring
domain/type_suggestion.py's DocumentTypeProposal for document types.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

RuleSeverity = Literal["info", "warning", "error"]


class RuleTestInput(BaseModel):
    """What a rule sees: `value` (rules over an attribute), `doc` (the
    document's fields), `case` (the semantic view, e.g. case.titular.persona.dni),
    `request` (the caller's process data) and, for reference_data rules,
    `reference_data`."""

    value: Any = None
    doc: dict[str, Any] = Field(default_factory=dict)
    case: dict[str, Any] = Field(default_factory=dict)
    request: dict[str, Any] = Field(default_factory=dict)
    reference_data: dict[str, Any] = Field(default_factory=dict)


class RuleTestCase(BaseModel):
    name: str = Field(description="What situation it tests, in Spanish.")
    input: RuleTestInput
    expect: Literal["pass", "fail"] = Field(description="'pass' if the condition must hold with this input; 'fail' if not.")


class RuleDraft(BaseModel):
    outcome: Literal["ok", "ambiguous"] = Field(
        description=(
            "'ambiguous' if the description is not enough to write a condition without inventing something (a threshold, a "
            "definition, which document): then write no CEL and give the questions. 'ok' if it can be done."
        )
    )
    questions: list[str] = Field(default_factory=list, description="Only if outcome is 'ambiguous': what is missing, as concrete questions in Spanish.")
    condition_cel: str | None = Field(
        default=None,
        description=(
            "CEL expression that evaluates the condition. Variables: value (the attribute's value, if the rule is about an "
            "attribute), doc.<field>, case.<role>.<entity>.<attribute>, request.<field>, and if the category is "
            "'reference_data' also reference_data.employee_code_exists."
        ),
    )
    applies_when_cel: str | None = Field(
        default=None,
        description=(
            "Optional additional CEL expression (never reference_data.) that must hold "
            "for the rule to apply. None if it does not apply."
        ),
    )
    severity: RuleSeverity = Field(default="warning", description="Severity when the condition does NOT hold.")
    message_pass: str = Field(default="", description="Message in Spanish when the condition holds.")
    message_fail: str = Field(default="", description="Message in Spanish when the condition does NOT hold.")
    rationale: str = Field(
        description="Brief explanation in Spanish of the logic of the generated CEL expression, so a person can review it."
    )
    test_cases: list[RuleTestCase] = Field(
        default_factory=list,
        description="If outcome is 'ok': at least one case that holds (expect 'pass') and one that does not (expect 'fail'), with realistic values.",
    )

    @model_validator(mode="after")
    def _complete(self) -> RuleDraft:
        if self.outcome == "ambiguous":
            if not self.questions:
                raise ValueError("outcome 'ambiguous' necesita al menos una pregunta")
            return self
        if not self.condition_cel:
            raise ValueError("outcome 'ok' necesita condition_cel")
        if {c.expect for c in self.test_cases} != {"pass", "fail"}:
            raise ValueError("outcome 'ok' necesita al menos un caso de prueba 'pass' y uno 'fail'")
        return self
