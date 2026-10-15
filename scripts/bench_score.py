"""Scores bench_extraction.py runs against values verified by hand in the
documents' images — never against an earlier run, which has its own errors
(docs/eficiencia-modelos-ia.md).

    uv run python scripts/bench_score.py base1 base2 base3                  # each run, field by field
    uv run python scripts/bench_score.py --group antes=base* --group ahora=new*   # mean and range per group

Reads BENCH_DIR (default ~/.veritium/bench): runs/<label>.json and truth.json.
truth.json, per document type, holds the expected value of each field (the
example below is invented):

    {"payslip": {"employee_name": "PEREZ ROJAS ANA", "net_pay": 2500.0, "#concepts": 12},
     "foreign_resident_id": {"001234567": {"surnames": "PEREZ ROJAS", "issue_date": "05 Ene 2020"}}}

"#<list>" is how many items a list must have; a document with several people
(persons[]) is keyed by each person's id number, so their order does not count.
Numbers compare to two decimals; text without accents, case or extra spaces.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import unicodedata
from pathlib import Path

BENCH = Path(os.environ.get("BENCH_DIR", "~/.veritium/bench")).expanduser()


def _norm(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)
    text = " ".join(unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().casefold().split())
    try:
        return round(float(text.replace(",", "")), 2)
    except ValueError:
        return text


def _value(node: object) -> object:
    return node.get("value") if isinstance(node, dict) else node


def score(truth: dict, dtype: str, payload: dict | None) -> tuple[int, int, list[str]]:
    expected, payload = truth[dtype], payload or {}
    ok, missed = 0, []
    if dtype == "foreign_resident_id":  # several people, matched by id number
        people = {re.sub(r"\D", "", str(_value(p.get("foreigner_id_number")) or "")): p for p in payload.get("persons", [])}
        checks = [(f"{num}.{k}", v, _value(people.get(num, {}).get(k))) for num, fields in expected.items() for k, v in fields.items()]
    else:
        checks = [(k, v, len(payload.get(k[1:]) or []) if k.startswith("#") else _value(payload.get(k))) for k, v in expected.items()]
    for name, want, got in checks:
        if _norm(got) == _norm(want):
            ok += 1
        else:
            missed.append(f"{name}={got!r}")
    return ok, len(checks), missed


def _run(label: str) -> dict:
    return json.loads((BENCH / "runs" / f"{label}.json").read_text())


def _totals(truth: dict, run: dict) -> tuple[float, float, int, int]:
    ok = n = 0
    for doc in run.values():
        a, b, _ = score(truth, doc["type"], doc["payload"])
        ok, n = ok + a, n + b
    seconds = sum(d["seconds"] for d in run.values())
    output = sum(t["out"] or 0 for d in run.values() for t in d["turns"])
    # cut at the cap: seen as such (no retry), or asked again by the port (llm/port.py)
    capped = sum(d.get("loop_retries", 0) + sum("LENGTH" in str(t.get("finish")) for t in d["turns"]) for d in run.values())
    errors = sum(len(d.get("model_errors", [])) for d in run.values())  # runs before the count existed: 0
    return ok / n, seconds, output, capped, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", nargs="*")
    parser.add_argument("--group", action="append", default=[], help="nombre=patrón (glob sobre runs/)")
    args = parser.parse_args()
    truth = json.loads((BENCH / "truth.json").read_text())
    for label in args.labels:
        run = _run(label)
        print(f"== {label}")
        for name, doc in run.items():
            ok, n, missed = score(truth, doc["type"], doc["payload"])
            print(f"  {doc['type']:22} {ok:2}/{n:2} {doc['seconds']:7.1f}s {len(doc['turns'])} turnos  ✗ {', '.join(missed)[:150]}")
        acc, seconds, output, capped, errors = _totals(truth, run)
        print(f"  TOTAL {acc:.0%} · {seconds:.0f}s · {output} tok de salida · {capped} turnos al tope · {errors} errores del modelo")
    for spec in args.group:
        name, pattern = spec.split("=", 1)
        runs = [_totals(truth, json.loads(p.read_text())) for p in sorted((BENCH / "runs").glob(f"{pattern}.json"))]
        if not runs:
            print(f"== {name}: sin corridas")
            continue

        def fmt(i: int, scale: float = 1, unit: str = "", runs: list = runs) -> str:
            v = [r[i] * scale for r in runs]
            return f"{statistics.mean(v):.0f}{unit} ({min(v):.0f}–{max(v):.0f})"

        print(f"== {name}: {len(runs)} corridas · exactitud {fmt(0, 100, '%')} · tiempo {fmt(1, unit=' s')} · salida {fmt(2, unit=' tok')} · turnos al tope {fmt(3)} · errores del modelo {fmt(4)}")


if __name__ == "__main__":
    main()
