"""The tool catalog (VRT-53), read-only.

GET /v1/tools       every tool: what it does, deterministic or model, cost, who may use it, internal or exposed
GET /v1/tools/mcp   the exposed ones as MCP descriptors (inputSchema / outputSchema / annotations), with the
                    catalog's data under ``_meta`` — what another platform (e.g. aeon's tool gateway) needs to
                    list them in its own catalog."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from idp.api.deps import get_current_user
from idp.tools.catalog import CATALOG

router = APIRouter(prefix="/v1/tools", tags=["tools"], dependencies=[Depends(get_current_user)])

META = "pe.veritium/catalog"


@router.get("")
async def list_tools() -> list[dict[str, Any]]:
    return [s.view() for s in CATALOG.values()]


@router.get("/mcp")
async def mcp_descriptors(request: Request) -> dict[str, Any]:
    tools = await request.app.state.mcp.list_tools()
    out = []
    for tool in tools:
        descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        spec = CATALOG[tool.name]
        descriptor["_meta"] = {**descriptor.get("_meta", {}), META: {"kind": spec.kind, "cost": spec.cost, "roles": list(spec.roles)}}
        out.append(descriptor)
    return {"server": request.app.state.mcp.name, "endpoint": "/mcp", "tools": out}
