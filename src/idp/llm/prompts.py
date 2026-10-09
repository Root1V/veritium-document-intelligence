"""Versioned prompts (VRT-46). Every fixed instruction the platform gives a
model is registered by name; its version is a fingerprint of its text, so
editing a prompt changes its version without anyone remembering to bump
it. A call passes the rendered prompt as a synaptum ``PromptTemplate``
carrying that name and version, which synaptum stamps on the model step in
its journal and on the span (S-8). ``versions()`` is what a case run and an
evaluation run record in their provenance.

The text in effect (VRT-63) is, in order: a draft an evaluation run is
trying (``trial``, for that run only), the text an AI specialist published
(``set_published``, loaded from the database), or the text in the code."""

from __future__ import annotations

import hashlib
import importlib
import string
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from synaptum import PromptTemplate

# Modules that register prompts — imported by versions() so the registry is
# complete whatever has been imported so far.
_MODULES = (
    "idp.classification.classifier",
    "idp.classification.type_discovery",
    "idp.classification.type_from_example",
    "idp.extraction.agentic.prompts",
    "idp.extraction.agentic.tools",
    "idp.extraction.generic",
    "idp.segmentation.splitter",
    "idp.validation.entity_matching",
    "idp.validation.rule_discovery",
    "idp.pipeline.lenses",
)


_PUBLISHED: dict[str, str] = {}
_TRIAL: ContextVar[dict[str, str] | None] = ContextVar("prompt_trial", default=None)


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:10]


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str  # as written in the code
    # The values the platform fills in each time, as {name} in the text. A
    # prompt that declares none is sent as is: its braces are literal.
    filled: tuple[str, ...] = ()

    @property
    def effective(self) -> str:
        """The text in effect: a draft on trial, the published one, or the code's."""
        return (_TRIAL.get() or {}).get(self.name) or _PUBLISHED.get(self.name) or self.text

    @property
    def version(self) -> str:
        return fingerprint(self.effective)

    @property
    def code_version(self) -> str:
        return fingerprint(self.text)

    def render(self, **values: Any) -> PromptTemplate:
        """The prompt with its values filled in, as a template that keeps its
        name and version. synaptum renders a template once more before
        sending it, so the braces of the rendered text are escaped: it
        arrives exactly as rendered here."""
        text = self.effective
        rendered = text.format(**values) if values else text
        return PromptTemplate(content=rendered.replace("{", "{{").replace("}", "}}"), version=fingerprint(text), name=self.name)

    def __str__(self) -> str:
        return self.effective


_REGISTRY: dict[str, Prompt] = {}


def prompt(name: str, text: str, *, filled: tuple[str, ...] = ()) -> Prompt:
    existing = _REGISTRY.get(name)
    if existing is not None and existing.text != text:
        raise ValueError(f"el prompt '{name}' ya está registrado con otro texto")
    if filled and placeholders(text) != set(filled):
        raise ValueError(f"el prompt '{name}' declara {sorted(filled)} pero su texto usa {sorted(placeholders(text))}")
    _REGISTRY[name] = Prompt(name=name, text=text, filled=filled)
    return _REGISTRY[name]


# What each prompt is for, in the words of whoever reads the page about them.
INFO: dict[str, tuple[str, str]] = {
    "classify": ("Clasificación de documentos", "Decide qué tipo de documento es cada archivo que llega."),
    "segment": ("Separación de documentos", "Detecta cuándo un archivo trae varios documentos juntos y dónde empieza cada uno."),
    "extract_agentic": ("Extracción de datos", "Lee cada documento y saca sus datos con la cita de dónde está cada uno."),
    "extract_generic": ("Extracción sin tipo", "Saca los datos de un documento que no corresponde a ningún tipo conocido."),
    "read_table_region": ("Lectura de tablas", "Describe una tabla del documento cuando el texto no alcanza para leerla."),
    "read_figure_region": ("Lectura de figuras", "Describe un gráfico o figura del documento."),
    "entity_judge": ("Comparación de nombres", "Decide si dos nombres de documentos distintos son la misma persona o empresa cuando no es obvio."),
    "suggest_document_type": ("Sugerencia de tipos nuevos", "Propone un tipo de documento nuevo cuando llegan documentos que no encajan."),
    "propose_type_from_example": ("Tipo desde un ejemplo", "Propone los campos de un tipo nuevo a partir de un documento de ejemplo."),
    "draft_rule": ("Redacción de reglas", "Traduce una regla escrita en lenguaje natural a una condición verificable."),
    "lens_summary": ("Resumen para Riesgos", "Resume un expediente con lo que Riesgos necesita, citando la evidencia."),
    "lens_playbook": ("Revisión para Legal", "Revisa cada documento contra el playbook de Legal, citando la evidencia."),
}


# Prompts an evaluation run exercises — classify, then extract — so a change
# to one is published only after an evaluation tried it (VRT-63).
EVALUATED = {"classify", "extract_agentic", "extract_generic", "read_table_region", "read_figure_region"}


def current() -> list[Prompt]:
    """Every prompt in use, by name."""
    for module in _MODULES:
        importlib.import_module(module)
    return [p for _, p in sorted(_REGISTRY.items())]


def versions() -> dict[str, str]:
    return {p.name: p.version for p in current()}


def get(name: str) -> Prompt | None:
    current()
    return _REGISTRY.get(name)


def set_published(texts: dict[str, str]) -> None:
    """The texts AI specialists published (VRT-63), replacing the previous set."""
    _PUBLISHED.clear()
    _PUBLISHED.update(texts)


@contextmanager
def trial(texts: dict[str, str]) -> Iterator[None]:
    """Draft texts in effect for this context only — an evaluation run
    trying them. Tasks and threads started inside inherit them."""
    token = _TRIAL.set({**(_TRIAL.get() or {}), **texts})
    try:
        yield
    finally:
        _TRIAL.reset(token)


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def draft_problems(prompt: Prompt, text: str) -> list[str]:
    """Why a draft cannot replace a prompt: the values the platform fills in
    must all still be there, and nothing else in braces."""
    if not text.strip():
        return ["el texto está vacío"]
    required = set(prompt.filled)
    if not required:
        return []  # never filled in: braces are literal text
    try:
        found = placeholders(text)
    except ValueError as exc:
        return [f"llaves mal cerradas ({exc}); para escribir una llave literal usa {{{{ o }}}}"]
    problems = [f"falta {{{name}}}, que la plataforma completa en cada uso" for name in sorted(required - found)]
    problems += [f"{{{name}}} no es un dato que la plataforma complete aquí" for name in sorted(found - required)]
    return problems
