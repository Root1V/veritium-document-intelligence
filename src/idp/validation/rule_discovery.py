"""Drafts a CEL-backed validation rule from a human's plain-language
description — the 'self'/'request_input'/'reference_data' analog of
classification/type_discovery.py's document-type drafting. A human still
reviews/edits/activates the draft (api/routes/validation_rules.py); this
module never persists anything or makes a rule live."""

from __future__ import annotations

from idp.config import Settings
from idp.domain.rule_draft import RuleDraft
from idp.llm.port import structured
from idp.observability.otel import traced_llm_call

_SYSTEM_PROMPT = """Eres un agente que traduce una descripcion en lenguaje natural de una regla de \
validacion de negocio a una expresion CEL (Common Expression Language) segura y determinista.

Reglas del formato CEL disponible:
- Variables: doc.<nombre_de_campo> (campos del documento actual), request.<nombre_de_campo> \
(datos del payload de la solicitud, si el usuario los menciona), y SOLO si la categoria es \
"reference_data": reference_data.employee_code_exists (booleano precalculado que indica si el \
employee_code del documento existe en la base de referencia de empleados).
- Operadores: ==, !=, <, <=, >, >=, &&, ||, !, ?: (ternario).
- has(doc.campo) para verificar existencia antes de usar un campo (uso obligatorio si el campo \
puede estar ausente, para evitar errores en documentos donde ese campo no se extrajo).
- Strings: .matches(regex), .startsWith(...), .endsWith(...), .contains(...), size(...).
- Listas: .all(x, cond), .exists(x, cond), .filter(x, cond) para iterar sin loops arbitrarios.
- NO existen loops (for/while), ni llamadas a red, ni acceso a base de datos mas alla de \
reference_data.employee_code_exists — CEL es deliberadamente no Turing-completo y sin efectos \
secundarios. Si la descripcion del usuario requiere comparar contra OTRO documento del batch, o \
consultar un sistema externo, no es posible expresarlo en CEL: en ese caso, genera \
condition_cel="true" y explica la limitacion en rationale.

Genera:
1. condition_cel: la expresion CEL que evalua la condicion descrita. Usa has() para cualquier \
campo que no este garantizado presente.
2. applies_when_cel: expresion CEL adicional opcional (solo doc./request., nunca reference_data.) \
si la regla solo debe aplicar bajo cierta condicion mas alla del tipo de documento (None si no aplica).
3. severity: "error" para inconsistencias que bloquean, "warning" para revisar, "info" para \
solo informar.
4. message_pass / message_fail: mensajes breves en español para cuando la condicion se cumple o no.
5. rationale: explica en 1-2 frases la logica de la expresion generada, para que un humano \
revisor la pueda verificar sin tener que leer CEL."""


def draft_rule(
    settings: Settings,
    *,
    description: str,
    document_type: str,
    category: str,
    field_path: str | None,
    existing_fields_hint: list[str] | None = None,
) -> RuleDraft:
    fields_hint = f"\nCampos conocidos de {document_type}: {', '.join(existing_fields_hint)}." if existing_fields_hint else ""
    field_hint = f"\nCampo principal relacionado: {field_path}." if field_path else ""
    user_message = (
        f"Tipo de documento: {document_type}\nCategoria: {category}\nDescripcion de la regla: {description}"
        f"{field_hint}{fields_hint}"
    )
    with traced_llm_call(role="reasoning", model=settings.reasoning_model):
        return structured(
            purpose="draft_rule",
            role="reasoning",
            output=RuleDraft,
            instructions=_SYSTEM_PROMPT,
            task=user_message,
        )
