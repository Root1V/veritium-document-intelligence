"""The tool catalog (VRT-53): every tool Veritium's agents use or expose,
defined once — what it does (the description the model reads), whether it
is deterministic or calls a model, what it costs, who may use it, and
whether it stays internal or is exposed over MCP. The MCP server builds its
tools from here and enforces ``roles`` from here; the extraction agent's
tools take their description from here.

Exposure follows one criterion: MCP only where a process, owner or trust
boundary is crossed. The extraction agent's region tools stay internal —
in process, over a document it already holds — and so do the pipeline's
steps (classify, extract, split): exposing them would let a caller skip
the profile and the verdict, and tie clients to internals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

Kind = Literal["deterministic", "model"]
# ninguno: memory only · lectura: reads the database · modelo: one model call
# · procesamiento: opens or re-runs a case (minutes, several model calls)
Cost = Literal["ninguno", "lectura", "modelo", "procesamiento"]
Exposure = Literal["internal", "mcp"]

EVERYONE = ("visor", "operador", "admin", "integracion", "especialista_ia")
WRITERS = ("integracion", "operador", "admin")
AGENT = ("agente-extraccion",)  # Veritium's own extraction agent


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    kind: Kind
    cost: Cost
    exposure: Exposure
    roles: tuple[str, ...]
    read_only: bool
    idempotent: bool = True

    def view(self) -> dict[str, Any]:
        return asdict(self)


_SPECS = (
    # --- Internal: the extraction agent's tools (VRT-30), over one parsed document ---
    ToolSpec(
        "read_text_region", "Leer texto de regiones",
        "Lee el texto ya extraido (OCR) de una o varias regiones del documento por su region_id. Gratis, sin llamada a modelo de vision. "
        "Prefiere pasar VARIOS region_ids en una sola llamada (p. ej. todos los de una fila de tabla) en vez de una llamada por region — "
        "cada llamada consume un turno del presupuesto acotado del agente.",
        kind="deterministic", cost="ninguno", exposure="internal", roles=AGENT, read_only=True,
    ),
    ToolSpec(
        "read_table_region", "Leer una tabla",
        "Envia la imagen recortada de una region de tipo tabla a un modelo de vision para interpretar su contenido estructurado.",
        kind="model", cost="modelo", exposure="internal", roles=AGENT, read_only=True,
    ),
    ToolSpec(
        "read_figure_region", "Leer una figura",
        "Envia la imagen recortada de una region de tipo figura/grafico a un modelo de vision para interpretar su contenido.",
        kind="model", cost="modelo", exposure="internal", roles=AGENT, read_only=True,
    ),
    # --- Exposed over MCP (VRT-51): the decision service ---
    ToolSpec(
        "list_processes", "Procesos disponibles", "Los procesos que Veritium sabe revisar y qué documentos pide cada uno.",
        kind="deterministic", cost="lectura", exposure="mcp", roles=EVERYONE, read_only=True,
    ),
    ToolSpec(
        "submit_case", "Abrir un expediente",
        "Abre un expediente bajo un proceso (`profile`, de list_processes) con sus documentos por referencia (`documents[].url`: s3:// o https:// "
        "de un origen autorizado). `external_ref` es tu identificador; `request_id` hace la llamada repetible sin duplicar. Responde enseguida; "
        "el veredicto llega en minutos.",
        kind="model", cost="procesamiento", exposure="mcp", roles=WRITERS, read_only=False,
    ),
    ToolSpec(
        "add_documents", "Agregar documentos",
        "Agrega documentos a un expediente (por `case_id` o por tu `external_ref`) y lo vuelve a revisar.",
        kind="model", cost="procesamiento", exposure="mcp", roles=WRITERS, read_only=False,
    ),
    ToolSpec(
        "get_case_status", "Estado del expediente",
        "En qué etapa va el expediente: recibido, lectura, clasificación, extracción, validación, decisión.",
        kind="deterministic", cost="lectura", exposure="mcp", roles=EVERYONE, read_only=True,
    ),
    ToolSpec(
        "get_case_result", "Resultado del expediente",
        "El veredicto (continuar, revisión humana o devolver al cliente), sus motivos, lo que falta y los documentos. El detalle completo, "
        "con la evidencia de cada dato, está en el recurso `result_uri`.",
        kind="deterministic", cost="lectura", exposure="mcp", roles=EVERYONE, read_only=True,
    ),
    ToolSpec(
        "find_cases", "Buscar expedientes", "Expedientes por tu `external_ref`, o los más recientes.",
        kind="deterministic", cost="lectura", exposure="mcp", roles=EVERYONE, read_only=True,
    ),
    # --- Exposed over MCP (VRT-53): what agents that serve a customer or an analyst need ---
    ToolSpec(
        "request_documents_link", "Pedir documentos con un enlace",
        "Crea un enlace para que una persona suba sus documentos desde el teléfono; cada archivo se revisa al momento (nitidez, luz, tipo). "
        "Para un expediente nuevo indica `profile` (y si quieres `external_ref`, `process_data`); para completar uno, `case_id`. "
        "Devuelve el enlace a enviarle y cuándo vence; cuando la persona envía, el expediente se procesa.",
        kind="deterministic", cost="lectura", exposure="mcp", roles=WRITERS, read_only=False, idempotent=False,
    ),
    ToolSpec(
        "quick_check_document", "Revisar un archivo en segundos",
        "Antes de enviar un documento: revisa si se puede leer (nitidez, luz, resolución, páginas en blanco, PDF dañado) y reconoce su tipo. "
        "El archivo va por referencia (`url`: s3:// o https:// de un origen autorizado); `expected_type` avisa si parece otro documento.",
        kind="model", cost="modelo", exposure="mcp", roles=EVERYONE, read_only=True,
    ),
    ToolSpec(
        "get_field_evidence", "Evidencia de un dato",
        "De dónde sale un dato del expediente (p. ej. el DNI del titular): su valor, si los documentos coinciden, y en cada documento el "
        "valor leído, la página, la posición y el texto de origen. `attribute` por clave ('persona.dni') o por nombre ('DNI'); `role` por "
        "defecto 'titular'.",
        kind="deterministic", cost="lectura", exposure="mcp", roles=EVERYONE, read_only=True,
    ),
    ToolSpec(
        "list_lenses", "Lentes de lectura", "Las lentes con que Riesgos o Legal leen un expediente (resumen o revisión de cláusulas).",
        kind="deterministic", cost="lectura", exposure="mcp", roles=EVERYONE, read_only=True,
    ),
    ToolSpec(
        "read_with_lens", "Leer un expediente con una lente",
        "La lectura de un expediente con una lente de Riesgos o Legal, con la cita de dónde lo dice cada documento. Si no hay una vigente la "
        "inicia (tarda alrededor de un minuto) y responde 'en curso': vuelve a llamar con los mismos datos para obtenerla.",
        kind="model", cost="modelo", exposure="mcp", roles=("operador", "admin", "especialista_ia"), read_only=False,
    ),
)

CATALOG: dict[str, ToolSpec] = {s.name: s for s in _SPECS}


def spec(name: str) -> ToolSpec:
    return CATALOG[name]


def exposed() -> list[ToolSpec]:
    return [s for s in _SPECS if s.exposure == "mcp"]
