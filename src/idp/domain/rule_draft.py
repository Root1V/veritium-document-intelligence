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
    name: str = Field(description="Qué situación prueba, en español.")
    input: RuleTestInput
    expect: Literal["pass", "fail"] = Field(description="'pass' si la condición debe cumplirse con este input; 'fail' si no.")


class RuleDraft(BaseModel):
    outcome: Literal["ok", "ambiguous"] = Field(
        description=(
            "'ambiguous' si la descripción no alcanza para escribir una condición sin inventar algo (un umbral, una "
            "definición, qué documento): entonces no escribas CEL y pon las preguntas. 'ok' si se puede."
        )
    )
    questions: list[str] = Field(default_factory=list, description="Solo si outcome es 'ambiguous': lo que falta saber, en preguntas concretas.")
    condition_cel: str | None = Field(
        default=None,
        description=(
            "Expresion CEL que evalua la condicion. Variables: value (el valor del atributo, si la regla es sobre un "
            "atributo), doc.<campo>, case.<rol>.<entidad>.<atributo>, request.<campo>, y si la categoria es "
            "'reference_data' tambien reference_data.employee_code_exists."
        ),
    )
    applies_when_cel: str | None = Field(
        default=None,
        description=(
            "Expresion CEL opcional adicional (nunca reference_data.) que debe cumplirse "
            "para que la regla aplique. None si no aplica."
        ),
    )
    severity: RuleSeverity = Field(default="warning", description="Severidad cuando la condicion NO se cumple.")
    message_pass: str = Field(default="", description="Mensaje en español cuando la condicion se cumple.")
    message_fail: str = Field(default="", description="Mensaje en español cuando la condicion NO se cumple.")
    rationale: str = Field(
        description="Explicacion breve de la logica de la expresion CEL generada, para que un humano la pueda revisar."
    )
    test_cases: list[RuleTestCase] = Field(
        default_factory=list,
        description="Si outcome es 'ok': al menos un caso que cumple (expect 'pass') y uno que no (expect 'fail'), con valores realistas.",
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
