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

_SYSTEM_PROMPT = prompt("draft_rule", """Eres un agente que traduce una descripcion en lenguaje natural de una regla de \
validacion de negocio a una expresion CEL (Common Expression Language) segura y determinista, con \
casos de prueba.

Variables disponibles en CEL:
- value: el valor del atributo, SOLO si la regla es sobre un atributo semantico (p. ej. ingreso.neto_mensual).
- doc.<campo>: campos del documento actual (reglas sobre un tipo de documento).
- case.<rol>.<entidad>.<atributo>: la vista consolidada del expediente (p. ej. case.titular.persona.dni), \
para comparar con otros datos del expediente.
- request.<campo>: datos del proceso que envio quien llama.
- SOLO si la categoria es "reference_data": reference_data.employee_code_exists (booleano precalculado).

Operadores: ==, !=, <, <=, >, >=, &&, ||, !, ?:. has(x.campo) antes de usar un campo que puede faltar. \
Strings: .matches(regex), .startsWith, .endsWith, .contains, size(). Listas: .all, .exists, .filter. \
No hay loops, red ni base de datos: CEL es no Turing-completo y sin efectos. CEL no compara enteros con \
decimales: los montos van con decimal, en la condicion y en los casos (1025.0, no 1025).

AMBIGUA: si la descripcion no alcanza para escribir la condicion sin inventar algo — un umbral sin numero \
("ingreso suficiente"), una definicion que no esta ("cliente valido"), datos de otro sistema — NO escribas \
CEL: responde outcome="ambiguous" con las preguntas concretas que lo resolverian. Inventar un umbral es peor \
que preguntar.

Si se puede (outcome="ok"), genera:
1. condition_cel: la condicion que debe CUMPLIRSE (si es falsa, la regla falla).
2. applies_when_cel opcional (sin reference_data.), o null.
3. severity: "error" bloquea, "warning" para revisar, "info" solo informa.
4. message_pass / message_fail breves en español.
5. rationale: la logica en 1-2 frases para que un humano la verifique sin leer CEL.
6. test_cases: al menos un caso que cumple (expect "pass") y uno que no (expect "fail"), con valores \
realistas en input (value, doc, case o request segun use la condicion).""")


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
        target = f"Regla sobre el atributo semantico {attribute}" + (
            f" ({definition.data_type}): {definition.definition} La condicion usa `value`." if definition else "."
        )
    else:
        target = f"Regla sobre el tipo de documento: {document_type}"
        if existing_fields_hint:
            target += f"\nCampos conocidos de {document_type}: {', '.join(existing_fields_hint)}."
    field_hint = f"\nCampo principal relacionado: {field_path}." if field_path else ""
    case_hint = (
        "\nAtributos del expediente disponibles en case.<rol>.<atributo>: " + ", ".join(a.key for a in semantic.attributes)
        if semantic is not None
        else ""
    )
    user_message = f"{target}\nCategoria: {category}\nDescripcion de la regla: {description}{field_hint}{case_hint}"
    with traced_llm_call(role="reasoning", model=model_for("reasoning")):
        return structured(
            purpose="draft_rule",
            role="reasoning",
            output=RuleDraft,
            instructions=_SYSTEM_PROMPT.render(),
            task=user_message,
        )
