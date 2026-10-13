"""Measures the extraction agent on real documents, turn by turn (VRT-69): seconds,
input/output/cached tokens, why each turn ended, which tool it called, how many
turns ran to the output cap and were asked again; and what it extracted, for
bench_score.py. Method and findings: docs/eficiencia-modelos-ia.md.

    uv run python scripts/bench_extraction.py <label> [--temperature T] [--reasoning-effort low|medium|high]

The data lives outside the repo (real documents carry personal data), in
BENCH_DIR (default ~/.veritium/bench):

    docs.txt            one document per line, "<path>:<document type>" (path relative to the repo or absolute)
    ocr-cache/          each document's reading, kept so repeated runs measure only the agent
    runs/<label>.json   this run's result
    capped.txt          what a turn that ran to the cap wrote (head and tail)

Every call goes without an idempotency key, so the gateway never replays an
earlier answer: each run is a real generation. Run variants interleaved and
several times each — one run of the agent decides nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import hashlib
import json
import logging
import os
import pickle
import time
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from synaptum import Sampling

from idp.config import Settings
from idp.llm import port
from idp.parsing.normalize import ParsedDocument
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import DocumentTypeRepository
from idp.pipeline.orchestrator import parse_example
from idp.pipeline.stages import extract_document

REPO = Path(__file__).resolve().parent.parent
BENCH = Path(os.environ.get("BENCH_DIR", "~/.veritium/bench")).expanduser()
CAP = 7000  # output tokens from which a turn counts as having run to the cap
TURNS: list[dict] = []


class _Retries(logging.Handler):
    """Counts the turns the port asked again after they ran to the cap (llm/port.py)."""

    count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "cortado" in record.getMessage():
            _Retries.count += 1


def _keep_capped(response) -> None:
    """What a turn that ran to the cap wrote: head and tail of each part."""
    with open(BENCH / "capped.txt", "a") as f:
        f.write(f"\n===== out={response.usage.output} finish={response.finish_reason}\n")
        for part in response.message.content:
            text = str(getattr(part, "text", "") or getattr(part, "arguments", "") or "")
            f.write(f"--- {type(part).__name__} ({len(text)} chars)\n{text[:1500]}\n[...]\n{text[-1500:]}\n")


def _measured(model):
    async def call(request, ctx=None):
        started = time.perf_counter()
        response = await model(request)  # no ctx: no idempotency key, no replay
        usage = response.usage
        TURNS.append({
            "s": round(time.perf_counter() - started, 1), "in": usage.input, "out": usage.output, "cache": usage.cache_read,
            "finish": str(response.finish_reason), "calls": [p.name for p in response.message.content if getattr(p, "kind", "") == "tool_call"],
        })
        if (usage.output or 0) >= CAP:
            _keep_capped(response)
        return response

    return call


async def _read(settings: Settings, path: Path) -> ParsedDocument:
    cache = BENCH / "ocr-cache" / (hashlib.md5(f"{path}|{settings.parser_backend}".encode()).hexdigest() + ".pkl")
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    started = time.perf_counter()
    parsed = await asyncio.to_thread(parse_example, settings, path.read_bytes(), path.name)
    print(f"   lectura {settings.parser_backend}: {time.perf_counter() - started:.1f}s, {parsed.page_count} págs", flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps(parsed))
    return parsed


async def main(label: str, temperature: float | None, effort: str | None) -> None:
    docs = [line.strip().rsplit(":", 1) for line in (BENCH / "docs.txt").read_text().splitlines() if line.strip()]
    settings = Settings()
    logging.getLogger("idp.llm.port").addHandler(_Retries())
    logging.getLogger("idp.llm.port").setLevel(logging.INFO)
    async with port.inference_lifespan(settings) as inference:
        inference._model_call = _measured(inference._model_call)
        if temperature is not None or effort:
            options = {"chat_template_kwargs": {"reasoning_effort": effort}} if effort else {}
            inference._sampling = lambda t=0.0: Sampling(  # type: ignore[method-assign]
                temperature=temperature if temperature is not None else t, max_output_tokens=settings.llm_max_output_tokens, provider_options=options
            )
        async with get_session_factory(settings)() as session:
            catalog = await DocumentTypeRepository(session).load_catalog()
        out = {}
        for raw, dtype in docs:
            path = Path(raw) if Path(raw).is_absolute() else REPO / raw
            parsed = await _read(settings, path)
            TURNS.clear()
            _Retries.count = 0
            started = time.perf_counter()
            try:
                result = await asyncio.to_thread(functools.partial(extract_document, settings, parsed, dtype, catalog, document_id=f"bench-{label}"))
                payload, error = (result.schema_instance.model_dump(mode="json") if result.schema_instance is not None else None), None
            except Exception as exc:  # noqa: BLE001 — measured, not raised: a failed document is a result
                payload, error = None, f"{type(exc).__name__}: {str(exc)[:200]}"
            seconds = round(time.perf_counter() - started, 1)
            name = path.name[:34]
            out[name] = {"type": dtype, "seconds": seconds, "turns": list(TURNS), "loop_retries": _Retries.count, "payload": payload, "error": error}
            print(f"{name:34} {dtype:22} {seconds:7.1f}s turnos={len(TURNS)} reintentos_por_tope={_Retries.count} {error or ''}", flush=True)
            for i, t in enumerate(TURNS, 1):
                print(f"   t{i}: {t['s']:6.1f}s in={t['in']} out={t['out']} cache={t['cache']} fin={t['finish']} {t['calls']}", flush=True)
    (BENCH / "runs").mkdir(parents=True, exist_ok=True)
    (BENCH / "runs" / f"{label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("label", help="nombre de la corrida (runs/<label>.json)")
    parser.add_argument("--temperature", type=float, help="temperatura para toda llamada (experimento)")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high"], help="esfuerzo de razonamiento de gpt-oss (experimento)")
    args = parser.parse_args()
    asyncio.run(main(args.label, args.temperature, args.reasoning_effort))
