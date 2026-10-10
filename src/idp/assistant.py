"""The user's assistant (VRT-54): a synaptum agent that answers a person's
questions about the platform and their cases through Veritium's own MCP
server, with the person's token — the same permissions, quota and access
as the person, without a second, privileged path to the data.

It only reads. The MCP tools that change something (open a case, add
documents, request documents, start a lens) stay as buttons in the UI,
where the person sees what they confirm; an assistant acting on a
misread question is worse than one that points to the button."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from pydantic import BaseModel, Field
from synaptum.core.errors import ProviderError
from synaptum.core.types import Risk
from synaptum.mcp import MCPTools

from idp.config import Settings
from idp.llm.port import inference
from idp.llm.prompts import prompt
from idp.pipeline.investigation import RETRY_TEMPERATURES, malformed
from idp.tools.catalog import CATALOG

log = logging.getLogger(__name__)

MCP_VERSION = "2026-07-28"

_INSTRUCTIONS = prompt("assistant", """Eres el asistente de Veritium, la plataforma que revisa los documentos de los expedientes de \
credito y decide si continuan, van a revision humana o se devuelven al cliente. Ayudas a personas de operaciones y negocio a \
buscar expedientes, entender en que etapa estan, por que tienen su veredicto, que falta y de donde sale cada dato.

Reglas:
- Responde solo con lo que devuelven tus herramientas; si no lo encuentras, dilo. Nunca inventes expedientes, datos ni motivos.
- Las personas nombran los expedientes por su codigo (p. ej. EXP-123): es su external_ref. Buscalo con find_cases para obtener su \
case_id (uuid) y usa ese id en las demas herramientas. Si la pregunta sigue sobre el mismo expediente, reutiliza el id.
- Habla en espanol, en lenguaje de negocio, breve: parrafos cortos o vinetas con '-'. Sin tablas ni JSON. Nombra los datos por su \
nombre de negocio ("ingreso bruto mensual", no gross_pay) y los expedientes por su name tal cual (p. ej. EXP-123 o \
Expediente 1a2b3c4d); nunca escribas un case_id ni un uuid: la pantalla pone el enlace a cada expediente que nombres.
- Solo consultas: no puedes abrir expedientes, agregar documentos ni pedirlos al cliente. Si te lo piden, explica que se hace desde \
la pantalla del expediente.
- Los numeros salen tal cual del campo summary de cada herramienta: copialos, no cuentes ni sumes listas (pueden venir recortadas).
- Si preguntan que expedientes, usa cases_overview: su summary y los expedientes que necesitan accion, por su name.
- Nunca nombres herramientas ni campos: habla de expedientes, datos y motivos.
- Los montos son en soles (S/) salvo que el documento diga otra moneda.""")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class AssistantAnswer(BaseModel):
    answer: str = Field(description="La respuesta para la persona, en espanol y en lenguaje de negocio.")


@dataclass
class Reply:
    answer: str
    seen: list[uuid.UUID]  # the cases its tools returned, in order: the only ones the answer may link to
    consulted: list[str]  # what it looked at, by the tools' titles


def mcp_url(settings: Settings) -> str:
    return settings.public_api_base_url.rstrip("/") + "/mcp"


_WEEKDAY = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def task(conversation: list[Turn], case_id: uuid.UUID | None, today: date) -> str:
    """The conversation so far, and the question to answer (the last turn)."""
    *earlier, question = conversation
    monday = today - timedelta(days=today.weekday())
    yesterday = today - timedelta(days=1)
    lines = [
        (
            f"Hoy es {_WEEKDAY[today.weekday()]} {today.isoformat()} (calendario del negocio). Rangos de fecha para las herramientas, inclusive: "
            f"hoy = {today} a {today}; ayer = {yesterday} a {yesterday}; esta semana = {monday} a {today}; "
            f"semana pasada = {monday - timedelta(days=7)} a {monday - timedelta(days=1)}; este mes = {today.replace(day=1)} a {today}."
        )
    ]
    if case_id is not None:
        lines.append(f"La persona esta viendo el expediente con id {case_id}.")
    if earlier:
        lines.append("Conversacion hasta ahora:")
        lines += [f"{'Persona' if t.role == 'user' else 'Asistente'}: {t.text}" for t in earlier]
    lines.append(f"Pregunta: {question.text}")
    return "\n".join(lines)


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


async def answer(settings: Settings, token: str, conversation: list[Turn], *, case_id: uuid.UUID | None = None) -> Reply:
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with http, Client(streamable_http_client(mcp_url(settings), http_client=http), mode=MCP_VERSION) as client:
        tools = [t for t in await MCPTools(client).discover() if t.definition.risk is Risk.READ]
        result: AssistantAnswer | None = None
        # Each question is its own run: the same words asked later must reach the model again, not replay the
        # first answer from the gateway's idempotency cache — the cases changed in between.
        run = uuid.uuid4().hex
        steps: list = []
        for attempt, temperature in enumerate(RETRY_TEMPERATURES):
            try:
                result, steps = await inference().run_agent(
                    purpose=f"assistant/{run}", instructions=_INSTRUCTIONS.render(), task=task(conversation, case_id, datetime.now(ZoneInfo(settings.business_timezone)).date()),
                    tools=tools, output=AssistantAnswer, max_steps=settings.assistant_max_turns, temperature=temperature,
                )
                break
            except ProviderError as exc:
                # Same as the investigator: a malformed tool call is retried once, sampling differently.
                if attempt == len(RETRY_TEMPERATURES) - 1 or not malformed(exc):
                    raise
                log.info("assistant: tool call malformed (%s); retrying at temperature %s", exc, RETRY_TEMPERATURES[attempt + 1])
    if result is None:
        raise ValueError("el asistente no entregó una respuesta")
    for s in steps:
        log.info("assistant: %s(%s)", s.call.name, s.call.arguments)
    seen = [uuid.UUID(m) for m in dict.fromkeys(m for s in steps if s.result is not None for part in s.result.content for m in UUID.findall(getattr(part, "text", "")))]
    consulted = list(dict.fromkeys(CATALOG[s.call.name].title if s.call.name in CATALOG else s.call.name for s in steps))
    return Reply(answer=result.answer, seen=seen, consulted=consulted)
