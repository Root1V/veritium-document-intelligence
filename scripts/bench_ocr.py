"""Compares OCR readers on the same pages (VRT-70): seconds per page, and how
far each one's lines are from the first reader's — the reference. Uses the
pipeline's own backends (parsing/), so it measures what production runs.

    uv run python scripts/bench_ocr.py paddleocr rapidocr

Pages come from the documents in BENCH_DIR/docs.txt (default ~/.veritium/bench),
as bench_extraction.py. Line agreement is a guide, not the verdict: two readers
that agree on boxes and key values can still differ in what the extraction
gets right, so a change of reader is decided with bench_extraction.py and
bench_score.py, end to end (docs/eficiencia-modelos-ia.md).
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import numpy as np
from rapidfuzz import fuzz, process

from idp.config import Settings
from idp.pipeline.orchestrator import make_parser_backend

REPO = Path(__file__).resolve().parent.parent
BENCH = Path(os.environ.get("BENCH_DIR", "~/.veritium/bench")).expanduser()


def _lines(backend: str, files: list[Path]) -> tuple[list[list[str]], float]:
    reader = make_parser_backend(Settings(parser_backend=backend))  # type: ignore[arg-type]
    reader.parse(files[0].read_bytes(), files[0].name)  # load the models outside the clock
    pages: list[list[str]] = []
    started = time.perf_counter()
    for f in files:
        parsed = reader.parse(f.read_bytes(), f.name)
        pages += [[b.text for b in parsed.blocks if b.text and b.page == i] for i in range(parsed.page_count)]
    return pages, (time.perf_counter() - started) / len(pages)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("backends", nargs="+", help="lectores a comparar; el primero es la referencia")
    args = parser.parse_args()
    files = [Path(p) if Path(p).is_absolute() else REPO / p for p in (line.strip().rsplit(":", 1)[0] for line in (BENCH / "docs.txt").read_text().splitlines() if line.strip())]
    reference, seconds = _lines(args.backends[0], files)
    print(f"{args.backends[0]:12} {seconds:5.1f} s/pág (referencia, {sum(map(len, reference))} líneas)")
    for backend in args.backends[1:]:
        pages, seconds = _lines(backend, files)
        scores = [process.extractOne(line, got, scorer=fuzz.ratio)[1] if got else 0 for ref, got in zip(reference, pages) for line in ref if len(line) >= 3]
        print(f"{backend:12} {seconds:5.1f} s/pág · similitud media {np.mean(scores):.1f} · idénticas {sum(s == 100 for s in scores)}/{len(scores)} · muy distintas (<70) {sum(s < 70 for s in scores)}")


if __name__ == "__main__":
    main()
