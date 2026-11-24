"""Veritium as an MCP server (VRT-51): other agents use it as a tool."""

from idp.mcp_server.server import app, build, llms_txt

__all__ = ["app", "build", "llms_txt"]
