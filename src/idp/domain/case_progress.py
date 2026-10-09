"""Where a case is in its processing (VRT-64), as a funnel of steps a
person can follow: received, reading, classification, data extraction,
validation, decision. Each step is done, running, pending or failed, with
how many documents went through it. Pure: derived from the status of
each document and of the latest run."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

StepState = Literal["done", "running", "pending", "failed"]

# How far a document has gone, by its status (persistence/models.py::Document).
_RANK = {"uploaded": 0, "reextract": 0, "parsing": 1, "classifying": 2, "extracting": 3, "extracted": 4, "validating": 5, "completed": 6, "needs_review": 6}
# (key, label, what it says while running, rank while in it, rank once past it)
_DOCUMENT_STEPS = (
    ("reading", "Lectura", "Leyendo documentos", 1, 2),
    ("classification", "Clasificación", "Clasificando documentos", 2, 3),
    ("extraction", "Extracción de datos", "Extrayendo datos", 3, 4),
    ("validation", "Validación", "Validando", 5, 6),
)
CASE_STATUS = {"uploaded": "En cola", "processing": "En proceso", "completed": "Terminado", "failed": "Con error", "submitted": "Recibido"}


class Step(BaseModel):
    key: str
    label: str
    state: StepState
    done: int = 0
    total: int = 0


class Progress(BaseModel):
    status_label: str  # the case's status, in words
    steps: list[Step]
    current: str  # what is happening now, e.g. "Extrayendo datos · 2 de 4 documentos"
    failed_documents: int


def progress(case_status: str, run_status: str | None, document_statuses: list[str]) -> Progress:
    """``document_statuses``: the logical documents of the case (a file that
    was split counts by its parts, not by itself)."""
    statuses = [s for s in document_statuses if s != "segmented"]
    total = len(statuses)
    failed = sum(s == "failed" for s in statuses)
    ranks = [_RANK.get(s, 0) for s in statuses if s != "failed"]
    run_finished = run_status in ("completed", "failed")
    steps = [Step(key="received", label="Recibido", state="done" if total else "pending", done=total, total=total)]
    current = "Esperando documentos" if not total else ""

    for key, label, doing, in_rank, past_rank in _DOCUMENT_STEPS:
        past = sum(r >= past_rank for r in ranks) + failed
        running = any(r == in_rank for r in ranks)
        if run_status == "completed" or (total and past == total):
            state: StepState = "done"
        elif running or (0 < past < total and not run_finished):
            state = "running"
        elif run_status == "failed" and past < total:
            state = "failed"
        else:
            state = "pending"
        if state == "pending" and run_status == "running" and steps[-1].state == "done":
            state = "running"  # between steps: the run already moved on to this one
        steps.append(Step(key=key, label=label, state=state, done=past, total=total))
        if state == "running" and not current:
            current = f"{doing} · {past} de {total} {'documento' if total == 1 else 'documentos'}"

    decision: StepState = "done" if run_status == "completed" else "failed" if run_status == "failed" else "pending"
    if decision == "pending" and run_status == "running" and all(s.state == "done" for s in steps):
        decision = "running"
    steps.append(Step(key="decision", label="Decisión", state=decision))

    if run_status == "failed":
        current = "El proceso se detuvo por un error"
    elif decision == "running":
        current = "Decidiendo el veredicto"
    elif decision == "done":
        current = "Terminado"
    elif not current and run_status in ("queued", "pending", None) and total:
        current = "En cola"
    if failed and decision != "failed":
        current += f" · {failed} {'documento' if failed == 1 else 'documentos'} con error"
    return Progress(status_label=CASE_STATUS.get(case_status, case_status), steps=steps, current=current, failed_documents=failed)
