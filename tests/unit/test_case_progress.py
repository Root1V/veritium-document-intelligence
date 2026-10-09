"""Unit tests for VRT-64: where a case is in its processing."""

from __future__ import annotations

from idp.domain.case_progress import progress


def _states(p) -> list[str]:
    return [s.state for s in p.steps]


def test_documents_halfway_through_extraction() -> None:
    p = progress("processing", "running", ["extracted", "extracting", "parsing", "segmented"])
    assert _states(p) == ["done", "running", "running", "running", "pending", "pending"]
    assert p.current == "Leyendo documentos · 2 de 3 documentos"
    assert p.steps[3].done == 1 and p.status_label == "En proceso"


def test_all_extracted_the_run_moves_on_to_validation() -> None:
    p = progress("processing", "running", ["extracted", "extracted"])
    assert _states(p) == ["done", "done", "done", "done", "running", "pending"]
    assert p.current == "Validando · 0 de 2 documentos"


def test_a_finished_case_with_a_failed_document() -> None:
    p = progress("completed", "completed", ["completed", "failed", "needs_review"])
    assert set(_states(p)) == {"done"} and p.current == "Terminado · 1 documento con error"


def test_a_run_that_stopped() -> None:
    p = progress("failed", "failed", ["extracted", "parsing"])
    assert _states(p)[-1] == "failed" and p.current == "El proceso se detuvo por un error"


def test_waiting_in_the_queue() -> None:
    p = progress("uploaded", "pending", ["uploaded", "uploaded"])
    assert _states(p) == ["done", "pending", "pending", "pending", "pending", "pending"] and p.current == "En cola"
