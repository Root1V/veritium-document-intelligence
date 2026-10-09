"""Versioned prompts (VRT-46). Every fixed instruction the platform gives a
model is registered by name; its version is a fingerprint of its text, so
editing a prompt changes its version without anyone remembering to bump
it. A call passes the rendered prompt as a synaptum ``PromptTemplate``
carrying that name and version, which synaptum stamps on the model step in
its journal and on the span (S-8). ``versions()`` is what a case run and an
evaluation run record in their provenance."""

from __future__ import annotations

import hashlib
import importlib
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


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str

    @property
    def version(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:10]

    def render(self, **values: Any) -> PromptTemplate:
        """The prompt with its values filled in, as a template that keeps its
        name and version. synaptum renders a template once more before
        sending it, so the braces of the rendered text are escaped: it
        arrives exactly as rendered here."""
        rendered = self.text.format(**values) if values else self.text
        return PromptTemplate(content=rendered.replace("{", "{{").replace("}", "}}"), version=self.version, name=self.name)

    def __str__(self) -> str:
        return self.text


_REGISTRY: dict[str, Prompt] = {}


def prompt(name: str, text: str) -> Prompt:
    existing = _REGISTRY.get(name)
    if existing is not None and existing.text != text:
        raise ValueError(f"el prompt '{name}' ya está registrado con otro texto")
    _REGISTRY[name] = Prompt(name=name, text=text)
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


def current() -> list[Prompt]:
    """Every prompt in use, by name."""
    for module in _MODULES:
        importlib.import_module(module)
    return [p for _, p in sorted(_REGISTRY.items())]


def versions() -> dict[str, str]:
    return {p.name: p.version for p in current()}
