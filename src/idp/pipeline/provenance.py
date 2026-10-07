"""What produced a case run's result (VRT-25): enough to explain it and to
reproduce it later. Stored on ``CaseRun.provenance``. Prompts live in code
today, so ``code_version`` pins them; per-prompt versions arrive with
synaptum's prompt registry (VRT-46)."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from idp.config import Settings
from idp.persistence.models import ProcessProfileVersion
from idp.validation.base import ValidationRule
from idp.validation.rules.generic import DataDrivenRule


@lru_cache(maxsize=1)
def code_version() -> str:
    """The deployed commit: ``VERITIUM_CODE_VERSION`` when the deployment
    sets it, else ``git rev-parse`` on a checkout, else 'unknown'."""
    if env := os.environ.get("VERITIUM_CODE_VERSION"):
        return env
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _package_version() -> str:
    try:
        return version("idp")
    except PackageNotFoundError:
        return "unknown"


def build_provenance(
    settings: Settings,
    *,
    profile_version: ProcessProfileVersion | None,
    rules: list[ValidationRule],
) -> dict[str, Any]:
    profile = None
    if profile_version is not None:
        profile = {
            "key": profile_version.profile.key,
            "version": profile_version.version,
            "content_hash": profile_version.content_hash,
            "semantic_catalog_version": profile_version.semantic_catalog_version,
        }
    return {
        "code_version": code_version(),
        "package_version": _package_version(),
        "profile": profile,
        # Filled in once resolution actually loads it (see orchestrator).
        "semantic_catalog_version": None,
        "models": {"reasoning": settings.reasoning_model, "vision": settings.vision_model},
        "parser_backend": settings.parser_backend,
        "thresholds": {
            "classification_confidence": settings.classification_confidence_threshold,
            "review_confidence": settings.review_confidence_threshold,
        },
        "rules": [
            {"rule_id": r.rule_id, "kind": "cel", "version": r.definition_version}
            if isinstance(r, DataDrivenRule)
            else {"rule_id": r.rule_id, "kind": "code", "version": code_version()}
            for r in rules
        ],
    }
