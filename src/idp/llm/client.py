"""OpenAI-compatible client for the one caller that still talks to the
reasoning server directly: the agentic extraction loop, until it moves onto
a synaptum ``Agent`` (VRT-30). Every other model call goes through
``idp.llm.port`` (VRT-29)."""

from __future__ import annotations

from openai import OpenAI

from idp.config import Settings


def make_client(settings: Settings) -> OpenAI:
    # Explicit timeout: without one, a stalled connection blocks a
    # document's processing for the SDK's 10-minute default.
    return OpenAI(base_url=settings.reasoning_base_url, api_key=settings.reasoning_api_key, timeout=settings.llm_request_timeout_seconds)
