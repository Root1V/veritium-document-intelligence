"""The tool catalog (VRT-53): one definition per tool, that the extraction
agent and the MCP server both read."""

from __future__ import annotations

from idp.extraction.agentic.tools import draft_tool, region_tools
from idp.tools.catalog import CATALOG, exposed, spec


def test_the_agent_reads_its_tools_descriptions_from_the_catalog():
    tools = [*region_tools(None), draft_tool(None)]  # type: ignore[arg-type] — only the definitions are read
    assert {t.name for t in tools} == {s.name for s in CATALOG.values() if "agente-extraccion" in s.roles}
    for t in tools:
        assert t.definition.description == spec(t.name).description


def test_every_tool_says_who_may_use_it_and_what_it_costs():
    for s in CATALOG.values():
        assert s.roles and s.description and s.title
        assert s.kind == "model" or s.cost in ("ninguno", "lectura"), f"{s.name}: a deterministic tool does not call a model"
        assert (s.exposure == "internal") == all(r.startswith("agente-") for r in s.roles), f"{s.name}: internal tools are for Veritium's own agents"


def test_pipeline_steps_are_not_exposed():
    assert {s.name for s in exposed()}.isdisjoint({"read_text_region", "read_table_region", "read_figure_region", "check_draft"})
