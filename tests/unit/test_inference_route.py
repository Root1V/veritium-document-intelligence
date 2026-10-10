"""Every model call goes synaptum → axonium → prometheus (VRT-29): no other
model client in the code or the dependencies, and no model endpoint or id
configured — the client's grants in prometheus decide the models."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from idp.config import Settings

ROOT = Path(__file__).resolve().parents[2]
_OTHER_CLIENTS = re.compile(r"^\s*(?:import|from)\s+(openai|instructor|litellm|anthropic|ollama|langchain\w*)\b", re.MULTILINE)


def test_no_model_client_but_axonium_in_the_code():
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        source = path.read_text()
        offenders += [f"{path.relative_to(ROOT)}: {m.group(1)}" for m in _OTHER_CLIENTS.finditer(source)]
        if "chat/completions" in source:
            offenders.append(f"{path.relative_to(ROOT)}: chat/completions")
    assert offenders == []


def test_no_model_client_but_axonium_in_the_dependencies():
    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    names = {re.split(r"[<>=!~\[ ]", d, maxsplit=1)[0].lower() for d in dependencies}
    assert not names & {"openai", "instructor", "litellm", "anthropic", "ollama"} and {"axonium", "synaptum"} <= names


def test_no_model_endpoint_or_id_is_configured():
    fields = set(Settings.model_fields)
    assert not {f for f in fields if re.match(r"(reasoning|vision)_(base_url|model|api_key)$", f)}
