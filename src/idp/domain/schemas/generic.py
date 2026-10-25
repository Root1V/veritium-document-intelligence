"""Fallback schema for documents that failed classification (unknown type or
low classification confidence). No fixed field set is assumed — this is
precisely the case where there is no known 'where does field X live', so the
generic extractor does a single best-effort pass, not the bounded agentic
loop used by schema-driven extractors (see extraction/registry.py)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from idp.domain.envelope import Extracted


class GenericField(BaseModel):
    key: str = Field(description="Name of the data in Spanish, as a person would read it (e.g. 'Monto solicitado').")
    value: Extracted[str]


class GenericSchema(BaseModel):
    fields: list[GenericField] = Field(default_factory=list)
    summary: Extracted[str] | None = None
