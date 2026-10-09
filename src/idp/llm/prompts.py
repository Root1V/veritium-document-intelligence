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


def versions() -> dict[str, str]:
    for module in _MODULES:
        importlib.import_module(module)
    return {name: p.version for name, p in sorted(_REGISTRY.items())}
