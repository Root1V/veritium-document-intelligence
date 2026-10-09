"""System prompt construction for the bounded agentic extraction loop —
acotado al esquema objetivo: the agent is given the target Pydantic schema
and the document's detected regions, and told to inspect regions rather than
assume a fixed layout (the layout-drift problem this loop exists to solve).
Registered and versioned (VRT-46); optionally grounded in the business
meaning of each field, from the semantic catalog."""

from __future__ import annotations

from pydantic import BaseModel
from synaptum import PromptTemplate

from idp.llm.prompts import prompt
from idp.parsing.normalize import ParsedDocument

_EXTRACTION = prompt("extract_agentic", """Eres un agente de extraccion de datos de documentos empresariales. {hint}

El layout de este tipo de documento puede variar entre distintas plantillas de la empresa a lo largo \
del tiempo, por lo que debes inspeccionar activamente las regiones disponibles en vez de asumir una \
posicion fija para cada campo.

Regiones detectadas en el documento:
{regions}

Herramientas disponibles:
- read_text_region(region_ids): lee texto OCR ya extraido de una o VARIAS regiones a la vez (sin costo). \
SIEMPRE que necesites leer varias regiones relacionadas (p. ej. todos los codigos/conceptos/montos de una \
tabla de ingresos o descuentos), pasalas TODAS juntas en una sola llamada (region_ids=[85,86,87,88,89,...]) \
en vez de una llamada por region — cada llamada consume un turno de tu presupuesto acotado.
- read_table_region(region_id): interpreta visualmente una region de tipo tabla.
- read_figure_region(region_id): interpreta visualmente una region de tipo figura/grafico.
- submit(...): entrega el resultado final segun el esquema objetivo. Debes llamarla para terminar.

Esquema objetivo (JSON Schema):
{schema}
{grounding}
Instrucciones:
1. Identifica primero que regiones necesitas para los campos principales (no listas) del esquema, y \
leelas en la MENOR cantidad de llamadas posible agrupando varios region_ids por llamada.
2. Si el esquema tiene una lista de items (p. ej. conceptos/lineas), agrupa TODOS los region_ids de esa \
tabla en una o dos llamadas a read_text_region, no una llamada por celda.
3. Usa read_table_region/read_figure_region solo cuando el dato que necesitas esta en una tabla o figura \
que no se puede leer como texto plano.
4. Tienes un numero limitado de turnos. En cuanto tengas los campos requeridos (obligatorios) del esquema, \
llama a submit — no es necesario agotar todas las regiones ni completar listas opcionales si el \
presupuesto de turnos se esta agotando.
5. Cada campo del esquema requiere: value, page, bbox, confidence (0-1), source_text (el texto exacto \
de donde se extrajo el valor) y region_id — esto es obligatorio para poder auditar la extraccion despues. \
"region_id" DEBE ser el numero exacto de region_id (de la lista de regiones arriba) de donde sacaste el \
valor — esto es CRITICO cuando el mismo dato (p. ej. un monto) aparece repetido en mas de una region o \
pagina del documento (por ejemplo, un monto "solicitado" en una seccion y un monto "aprobado" distinto en \
otra): el region_id es lo unico que distingue de forma inequivoca de cual de las dos ocurrencias sacaste \
el valor. "page" DEBE ser exactamente el numero de "pagina" que aparece junto a ese region_id — nunca \
asumas que todo esta en la pagina 0, especialmente en documentos de varias paginas.
6. "value" debe ser el valor LIMPIO y semantico (sin el ":" u otro separador de la etiqueta del campo, \
sin espacios sobrantes, sin el nombre de la etiqueta). "source_text" en cambio debe ser el texto CRUDO \
tal como aparece en la region OCR, incluyendo cualquier separador o etiqueta — no los uniformes. \
Ejemplo: si la region dice "Apellidos y Nombres : SALAS SIGUAS, KATERIN KAROLA", value debe ser \
"SALAS SIGUAS, KATERIN KAROLA" (sin el ":" inicial) y source_text puede conservar el texto completo.
""")


def build_system_prompt(hint: str, schema_cls: type[BaseModel], parsed: ParsedDocument, grounding: dict[str, str] | None = None) -> PromptTemplate:
    """``hint`` is the document type's extraction hint (catalog, VRT-32);
    ``grounding`` the business meaning of each field (VRT-46). Without it
    the prompt is the same text it always was."""
    regions = "\n".join(f"- region_id={b.region_id} tipo={b.block_type} pagina={b.page} texto_ocr={b.text[:80]!r}" for b in parsed.blocks)
    meaning = ""
    if grounding:
        lines = "\n".join(f"- {field}: {text}" for field, text in grounding.items())
        meaning = f"\nSignificado de negocio de los campos (te ayuda a ubicar el dato correcto; no cambia el formato del esquema):\n{lines}\n"
    return _EXTRACTION.render(hint=hint, regions=regions, schema=schema_cls.model_json_schema(), grounding=meaning)
