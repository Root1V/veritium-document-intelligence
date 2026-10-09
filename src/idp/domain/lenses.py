"""Lenses (VRT-45): how a downstream area — Risk, Legal — reads a case. A
summary lens tells what matters to the area; a playbook lens checks each
clause or condition the area requires. Every statement cites the regions
of the documents it rests on, and a cited quote that is not in them is
flagged instead of shown as fact. Pure: the runner (pipeline/lenses.py)
gives the documents' text and calls the model."""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from idp.domain.semantic import SemanticCatalog
from idp.domain.semantic_resolution import ConsolidatedView
from idp.parsing.normalize import ParsedDocument

Area = Literal["riesgos", "legal"]
ClauseStatus = Literal["cumple", "no_cumple", "no_encontrado", "dudoso"]
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


class PlaybookItem(BaseModel):
    key: str
    label: str = Field(description="Lo que debe cumplirse, en palabras del área.")
    guidance: str = Field(default="", description="Cómo juzgarlo: qué cuenta como cumplido.")
    importance: Literal["alta", "media", "baja"] = "media"


class LensDefinition(BaseModel):
    key: str
    name: str
    area: Area
    description: str
    kind: Literal["summary", "playbook"]
    # Which documents it reads; empty = all of the case.
    document_types: list[str] = []
    instructions: str = Field(default="", description="Resumen: en qué enfocarse.")
    playbook: list[PlaybookItem] = []

    @model_validator(mode="after")
    def _shape(self) -> LensDefinition:
        if not _KEY.match(self.key):
            raise ValueError("la clave debe ser snake_case")
        if self.kind == "playbook" and not self.playbook:
            raise ValueError("un playbook necesita al menos un punto")
        keys = [i.key for i in self.playbook]
        if len(keys) != len(set(keys)) or not all(_KEY.match(k) for k in keys):
            raise ValueError("cada punto del playbook necesita una clave snake_case única")
        return self


# --- What the model answers ---------------------------------------------------


class CitedPoint(BaseModel):
    text: str = Field(description="Una afirmación breve, en español simple.")
    refs: list[str] = Field(default_factory=list, description="Referencias [dN:R] donde se apoya.")


class LensSummaryAnswer(BaseModel):
    headline: str = Field(description="Una o dos frases con lo esencial para el área.")
    points: list[CitedPoint] = Field(description="De 3 a 8 puntos clave.")
    attention: list[CitedPoint] = Field(default_factory=list, description="Alertas o datos faltantes.")


class ClauseAnswer(BaseModel):
    item_key: str
    status: ClauseStatus
    explanation: str = Field(description="Por qué, en una o dos frases simples.")
    quote: str | None = Field(default=None, description="La cita textual más corta del documento que lo muestra.")
    refs: list[str] = Field(default_factory=list)


class PlaybookAnswer(BaseModel):
    headline: str
    checks: list[ClauseAnswer]


# --- Documents as the model reads them -----------------------------------------


class LensDocument(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    document_id: uuid.UUID
    document_type: str | None
    name: str  # display name of its type and file
    parsed: ParsedDocument
    page_start: int | None = None
    page_end: int | None = None


class Evidence(BaseModel):
    ref: str
    document_id: uuid.UUID
    document_name: str
    page: int
    bbox: list[float]
    text: str


MAX_CONTEXT_CHARS = 40_000


def _budgets(sizes: list[int], total: int) -> list[int]:
    """A fair share of the space: what a short document does not use is
    left for the long ones."""
    budgets = [0] * len(sizes)
    remaining, pending = total, sorted(range(len(sizes)), key=lambda i: sizes[i])
    while pending:
        share = remaining // len(pending)
        i = pending.pop(0)
        budgets[i] = min(sizes[i], share)
        remaining -= budgets[i]
    return budgets


def _lines(doc: LensDocument, n: int) -> list[tuple[str, Evidence]]:
    out = []
    for block in doc.parsed.blocks:
        if block.block_type == "figure" or not block.text.strip():
            continue
        if doc.page_start is not None and not (doc.page_start <= block.page <= (doc.page_end if doc.page_end is not None else doc.page_start)):
            continue
        ref = f"d{n}:{block.region_id}"
        out.append((f"[{ref}] {block.text.strip()}", Evidence(ref=ref, document_id=doc.document_id, document_name=doc.name, page=block.page, bbox=block.bbox, text=block.text)))
    return out


def render_facts(view: ConsolidatedView | None, catalog: SemanticCatalog | None, names: dict[uuid.UUID, str]) -> tuple[str, dict[str, Evidence]]:
    """The data the platform already extracted and reconciled across the
    case's documents, as numbered lines ``[f3] Titular · Ingreso neto
    mensual: 4304.14``, each pointing to where its first source says it.
    A model that starts from these does not have to rebuild them from OCR
    fragments, where a label and its value are often separate lines."""
    if view is None or not view.attributes:
        return "", {}
    attribute_names = {a.key: a.name for a in catalog.attributes} if catalog else {}
    role_names = {r.key: r.name for r in catalog.roles} if catalog else {}
    lines, index = ["=== Datos ya extraídos del expediente ==="], {}
    for n, a in enumerate(view.attributes, start=1):
        label = f"{role_names.get(a.role, a.role)} · {attribute_names.get(a.attribute, a.attribute)}"
        if a.status == "conflict":
            value = " / ".join(f"{s.value} ({names.get(s.document_id, s.document_type)})" for s in a.sources) + " — NO COINCIDEN"
        else:
            value = f"{a.value} ({', '.join(dict.fromkeys(names.get(s.document_id, s.document_type) for s in a.sources))})"
        ref = f"f{n}"
        lines.append(f"[{ref}] {label}: {value}")
        source = next((s for s in a.sources if s.page is not None and s.bbox), None)
        if source is not None and source.page is not None and source.bbox:
            index[ref] = Evidence(ref=ref, document_id=source.document_id, document_name=names.get(source.document_id, source.document_type),
                                  page=source.page, bbox=source.bbox, text=f"{label}: {source.value}")
    return "\n".join(lines), index


def render_context(documents: list[LensDocument], facts: str = "", fact_index: dict[str, Evidence] | None = None) -> tuple[str, dict[str, Evidence], bool]:
    """The extracted data first, then the documents as numbered lines
    ``[d1:31] texto``; what each reference points to; and whether some
    text had to be left out to fit."""
    index: dict[str, Evidence] = dict(fact_index or {})
    lines_by_doc = [_lines(doc, n) for n, doc in enumerate(documents, start=1)]
    sizes = [sum(len(line) for line, _ in lines) for lines in lines_by_doc]
    budgets = _budgets(sizes, MAX_CONTEXT_CHARS - len(facts))
    sections = [facts] if facts else []
    truncated = False
    for n, (doc, lines, budget) in enumerate(zip(documents, lines_by_doc, budgets, strict=True), start=1):
        out, used = [f"=== d{n}: {doc.name} ==="], 0
        for line, evidence in lines:
            if used + len(line) > budget:
                truncated = True
                break
            out.append(line)
            used += len(line)
            index[evidence.ref] = evidence
        sections.append("\n".join(out))
    return "\n\n".join(sections), index, truncated


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).casefold().split())


def quote_found(quote: str, evidence: list[Evidence]) -> bool:
    """Whether a quote is really in the cited regions (ignoring case,
    accents and spacing) — or, if none were cited, anywhere they could be."""
    return bool(quote.strip()) and _plain(quote) in _plain(" ".join(e.text for e in evidence))


# --- What a person reads ---------------------------------------------------------


class PointView(BaseModel):
    text: str
    evidence: list[Evidence]


class ClauseView(BaseModel):
    item_key: str
    label: str
    importance: str
    status: ClauseStatus
    explanation: str
    quote: str | None
    quote_verified: bool | None  # None: no quote given
    evidence: list[Evidence]


class LensOutput(BaseModel):
    headline: str
    points: list[PointView] = []
    attention: list[PointView] = []
    checks: list[ClauseView] = []
    truncated: bool = False
    unknown_refs: int = 0  # references the model invented: dropped


_REF = re.compile(r"\b([df]\d+)(?::(\d+)(?:\s*-\s*(\d+))?)?\b")
_REF_IN_TEXT = re.compile(r"\s*[\[(](?:\s*[df]\d+(?::\d+(?:\s*-\s*\d+)?)?\s*[,;]?)+[\])]")


def _expand(ref: str) -> list[str]:
    """``d2:142-143`` → ``d2:142``, ``d2:143``; ``f3`` stays ``f3``."""
    out = []
    for doc, start, end in _REF.findall(ref):
        if not start:
            out.append(doc)
        else:
            out += [f"{doc}:{n}" for n in range(int(start), int(end or start) + 1)][:20]
    return out


def _clean(text: str) -> tuple[str, list[str]]:
    """A statement without the references the model wrote into it, and those references."""
    refs = [r for m in _REF_IN_TEXT.finditer(text) for r in _expand(m.group(0))]
    return " ".join(_REF_IN_TEXT.sub("", text).split()), refs


def build_output(lens: LensDefinition, answer: LensSummaryAnswer | PlaybookAnswer, index: dict[str, Evidence], *, truncated: bool) -> LensOutput:
    unknown = 0

    def cite(refs: list[str]) -> list[Evidence]:
        nonlocal unknown
        wanted = list(dict.fromkeys(r for ref in refs for r in _expand(ref)))
        found = [index[r] for r in wanted if r in index]
        unknown += len(wanted) - len(found)
        return found

    def point(p: CitedPoint) -> PointView:
        text, in_text = _clean(p.text)
        return PointView(text=text, evidence=cite(p.refs + in_text))

    if isinstance(answer, LensSummaryAnswer):
        return LensOutput(
            headline=answer.headline,
            points=[point(p) for p in answer.points],
            attention=[point(p) for p in answer.attention],
            truncated=truncated,
            unknown_refs=unknown,
        )
    by_key = {c.item_key: c for c in answer.checks}
    checks = []
    for item in lens.playbook:
        c = by_key.get(item.key)
        if c is None:
            checks.append(ClauseView(item_key=item.key, label=item.label, importance=item.importance, status="dudoso",
                                     explanation="El análisis no se pronunció sobre este punto.", quote=None, quote_verified=None, evidence=[]))
            continue
        explanation, in_text = _clean(c.explanation)
        evidence = cite(c.refs + in_text)
        verified = quote_found(c.quote, evidence or list(index.values())) if c.quote else None
        checks.append(ClauseView(item_key=item.key, label=item.label, importance=item.importance, status=c.status,
                                 explanation=explanation, quote=c.quote, quote_verified=verified, evidence=evidence))
    return LensOutput(headline=answer.headline, checks=checks, truncated=truncated, unknown_refs=unknown)


# --- The lenses a fresh installation starts with -------------------------------

SEED_LENSES = [
    LensDefinition(
        key="riesgos_resumen_crediticio",
        name="Resumen crediticio",
        area="riesgos",
        description="Lo que Riesgos necesita saber del solicitante y del crédito, con la evidencia de cada dato.",
        kind="summary",
        instructions=(
            "Quién es el titular y su empleador; ingresos bruto y neto y descuentos; monto, plazo y cuota solicitados; "
            "qué parte del ingreso neto se va en la cuota; deudas que se compran o refinancian; y cualquier dato que no "
            "coincida entre documentos. Usa solo cifras que aparezcan en los documentos."
        ),
    ),
    LensDefinition(
        key="legal_autorizacion_descuento",
        name="Carta de autorización de descuento",
        area="legal",
        description="Revisa la carta de autorización de descuento por planilla contra lo que Legal exige.",
        kind="playbook",
        document_types=["authorization_letter"],
        playbook=[
            PlaybookItem(key="irrevocable", label="La autorización es irrevocable mientras exista deuda", importance="alta",
                         guidance="Debe decir que no puede revocarse, o que rige hasta cancelar el préstamo."),
            PlaybookItem(key="beneficiario", label="Identifica a la entidad que recibe el descuento", importance="alta",
                         guidance="Nombre de la entidad financiera beneficiaria."),
            PlaybookItem(key="monto", label="Indica la cuota o el monto máximo a descontar", importance="alta",
                         guidance="Un monto o una regla clara para calcularlo."),
            PlaybookItem(key="empleador", label="Identifica al empleador que aplica el descuento", importance="media"),
            PlaybookItem(key="firma_titular", label="Está firmada por el titular, con su nombre y DNI", importance="alta",
                         guidance="Nombre y DNI del titular junto a la firma o declaración de aceptación."),
        ],
    ),
    LensDefinition(
        key="legal_compra_deuda",
        name="Autorización de compra de deuda",
        area="legal",
        description="Revisa la autorización de subrogación o compra de deuda contra lo que Legal exige.",
        kind="playbook",
        document_types=["debt_subrogation_authorization"],
        playbook=[
            PlaybookItem(key="acreedor", label="Identifica la deuda y la entidad acreedora que se cancela", importance="alta"),
            PlaybookItem(key="monto", label="Indica el monto a pagar o cancelar", importance="alta"),
            PlaybookItem(key="instruccion", label="Instruye expresamente el pago a la entidad acreedora", importance="alta",
                         guidance="Una instrucción clara de pagar o transferir, no solo una mención."),
            PlaybookItem(key="firma_titular", label="Está firmada por el titular, con su nombre y DNI", importance="alta"),
        ],
    ),
]
