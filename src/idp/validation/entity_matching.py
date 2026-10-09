"""Shared fuzzy/dynamic entity-identity matching — used by both
``rules/batch_rules.py`` (category b) and ``rules/reference_data_rules.py``
(category d) whenever the comparison is identity ("is this the same
person/company/address"), not exact equality.

Algorithmic (``fuzzy_deterministic``) matching handles the vast majority of
real cases (abbreviations, missing middle names, reordered surnames, accents,
OCR noise) for free and reproducibly. A genuinely ambiguous middle band
escalates to a one-off LLM-judge call — never the default path, only the
fallback for cases the algorithm can't confidently resolve.

``jellyfish``'s phonetic algorithms were evaluated and rejected for Phase 0:
they're calibrated for English pronunciation and add no value over
``rapidfuzz`` + accent normalization on this Spanish-language corpus.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel
from rapidfuzz import distance, fuzz

from idp.config import Settings
from idp.llm.port import structured
from idp.llm.prompts import prompt

Band = Literal["match", "no_match", "ambiguous"]


class EntityKind(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    ADDRESS = "address"


_COMPANY_SUFFIXES = ["s.a.c.", "s.a.", "s.r.l.", "e.i.r.l.", "sac", "sa", "srl", "eirl"]


@dataclass(frozen=True)
class MatchOutcome:
    score: float
    band: Band
    normalized_a: str
    normalized_b: str
    metric: str


def normalize_text(text: str) -> str:
    """Accent/diacritic-insensitive, case-insensitive, whitespace-collapsed.
    Also strips commas/periods as separators — 'Santiago, Victor' and
    'Santiago Victor' should compare identically regardless of which
    convention (surnames-first-with-comma vs plain) a name was written in."""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(stripped.lower().replace(".", " ").replace(",", " ").split())


def _token_matches(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]  # "e" matches "emeric" — the abbreviated-initial case
    return False


def _initials_adjusted_ratio(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Token-set overlap that treats a single-letter token as matching the
    same-initial full token on the other side — resolves 'Emeric' vs 'E.'."""
    if not tokens_a or not tokens_b:
        return 0.0
    remaining = list(tokens_b)
    matched = 0
    for tok in tokens_a:
        for i, cand in enumerate(remaining):
            if _token_matches(tok, cand):
                matched += 1
                remaining.pop(i)
                break
    return matched / max(len(tokens_a), len(tokens_b))


def _strip_company_suffix(text: str) -> str:
    norm = normalize_text(text)
    for suffix in _COMPANY_SUFFIXES:
        if norm.endswith(f" {suffix}") or norm == suffix:
            return norm[: -len(suffix)].strip()
    return norm


def _band(score: float, *, high_threshold: float, low_threshold: float) -> Band:
    if score >= high_threshold:
        return "match"
    if score <= low_threshold:
        return "no_match"
    return "ambiguous"


def match_entities(
    kind: EntityKind,
    value_a: str,
    value_b: str,
    *,
    high_threshold: float,
    low_threshold: float,
) -> MatchOutcome:
    if kind is EntityKind.COMPANY:
        norm_a, norm_b = _strip_company_suffix(value_a), _strip_company_suffix(value_b)
    else:
        norm_a, norm_b = normalize_text(value_a), normalize_text(value_b)

    tokens_a, tokens_b = [t for t in norm_a.split(" ") if t], [t for t in norm_b.split(" ") if t]
    token_set_score = fuzz.token_set_ratio(norm_a, norm_b) / 100.0
    initials_score = _initials_adjusted_ratio(tokens_a, tokens_b)
    jw_score = distance.JaroWinkler.normalized_similarity(norm_a, norm_b)

    candidates = {"token_set_ratio": token_set_score, "initials": initials_score, "jaro_winkler": jw_score}
    metric, score = max(candidates.items(), key=lambda kv: kv[1])

    return MatchOutcome(
        score=score,
        band=_band(score, high_threshold=high_threshold, low_threshold=low_threshold),
        normalized_a=norm_a,
        normalized_b=norm_b,
        metric=metric,
    )


class EntityMatchVerdict(BaseModel):
    is_match: bool
    reasoning: str


_JUDGE_SYSTEM_PROMPT = prompt("entity_judge", """Eres un juez que determina si dos valores extraidos de documentos distintos \
se refieren a la misma entidad (persona, empresa o direccion). Considera abreviaturas, nombres \
compuestos, apodos y variaciones de formato. Responde con tu veredicto y una breve justificacion.""")


def escalate_to_llm_judge(settings: Settings, *, kind: EntityKind, value_a: str, value_b: str, outcome: MatchOutcome) -> EntityMatchVerdict:
    """Only reached for scores in the ambiguous band — reuses the same
    structured-output infrastructure as everything else in ``idp.llm``,
    the same escalation pattern already used by category (e)."""
    prompt = (
        f"Tipo de entidad: {kind.value}\n"
        f"Valor A: {value_a!r}\nValor B: {value_b!r}\n"
        f"Normalizados: {outcome.normalized_a!r} vs {outcome.normalized_b!r}\n"
        f"Score algoritmico ({outcome.metric}): {outcome.score:.2f} (banda ambigua)\n"
        "¿Se refieren a la misma entidad?"
    )
    return structured(
        purpose="entity_judge",
        role="reasoning",
        output=EntityMatchVerdict,
        instructions=_JUDGE_SYSTEM_PROMPT.render(),
        task=prompt,
    )
