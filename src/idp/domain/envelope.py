"""Citation envelope: the value object every extracted leaf field is wrapped in.

Grounding (page/bbox/source_text) is a first-class part of the schema, not a
bolt-on — every ``Extracted[T]`` field carries enough to answer "why was this
extracted as X" without a separate lookup. ``reasoning_trace`` additionally
records the bounded agentic extraction loop's tool calls when an extractor
used one (see ``idp.extraction.agentic``), giving "why did the agent look
here" for extractors whose method is not a single fixed prompt.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ToolCallRecord(BaseModel):
    """One turn of the bounded ReAct extraction loop: a tool call and its outcome."""

    turn: int
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: str
    reasoning: str | None = None


class Read(BaseModel, Generic[T]):
    """What the extraction agent writes for one field (VRT-69): the value and
    where it read it. Page and box are not asked of the model — grounding
    takes them from the region (extraction/grounding.py) — and every token it
    does not write is time saved: the agent's cost is its output."""

    value: T
    confidence: float = Field(ge=0.0, le=1.0)
    source_text: str | None = None
    region_id: int | None = None


class Extracted(BaseModel, Generic[T]):
    """A single extracted field, grounded back to its source document."""

    value: T
    page: int | None = None
    bbox: list[float] | None = None  # normalized [x1, y1, x2, y2] in [0, 1]
    confidence: float = Field(ge=0.0, le=1.0)
    source_text: str | None = None
    # Optional: the exact region_id (from the parsed document's block list,
    # shown to the agent in its system prompt) this value came from. When
    # present and valid, grounding uses it directly instead of matching
    # source_text against blocks — text-matching is ambiguous whenever the
    # same value legitimately appears on more than one page (e.g. a loan
    # amount repeated as both 'requested' on page 1 and 'approved' on page
    # 3) and region_id resolves that ambiguity exactly. See
    # extraction/grounding.py.
    region_id: int | None = None
    reasoning_trace: list[ToolCallRecord] | None = None
