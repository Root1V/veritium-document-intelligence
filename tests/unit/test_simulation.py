"""Unit tests for VRT-44's pure part: what changes between a real decision
and the candidate's, and the summary a person reads."""

from __future__ import annotations

from idp.domain.simulation import Outcome, difference, summarize


def _rule(document: str, message: str) -> dict:
    return {"kind": "rule", "ref": {"rule_id": "names", "document_id": document}, "message": message}


def test_reasons_are_compared_by_what_they_are_about_not_their_wording() -> None:
    actual = [
        {"kind": "missing_document", "ref": {"condition_key": "solicitud"}, "message": "Falta: Solicitud"},
        _rule("d1", "Nombre: 'A' (boleta) vs 'B' (seguro)"),
        _rule("d2", "Nombre: 'A' (boleta) vs 'B' (seguro)"),
    ]
    simulated = [
        _rule("d1", "Nombre: 'B' (seguro) vs 'A' (boleta)"),  # same facts, another order: not a change
        _rule("d2", "Nombre: 'B' (seguro) vs 'A' (boleta)"),
        {"kind": "missing_document", "ref": {"condition_key": "carta"}, "message": "Falta: Carta"},
    ]
    diff = difference(actual, simulated)
    assert diff.added_reasons == ["Falta: Carta"]
    assert diff.removed_reasons == ["Falta: Solicitud"]


def test_a_reason_on_two_documents_reads_once() -> None:
    assert difference([], [_rule("d1", "Nombre no coincide"), _rule("d2", "Nombre no coincide")]).added_reasons == ["Nombre no coincide"]


def test_summary_counts_changes_and_transitions() -> None:
    summary = summarize(
        [
            Outcome(actual_verdict="return_to_client", simulated_verdict="continue"),
            Outcome(actual_verdict="return_to_client", simulated_verdict="continue"),
            Outcome(actual_verdict="human_review", simulated_verdict="human_review"),
            Outcome(actual_verdict="continue", simulated_verdict="human_review"),
            Outcome(actual_verdict="continue", simulated_verdict=None, failed=True),
        ]
    )
    assert (summary.cases, summary.failed, summary.changed, summary.agreement) == (5, 1, 3, 0.25)
    assert summary.before == {"return_to_client": 2, "human_review": 1, "continue": 1}
    assert summary.after == {"continue": 2, "human_review": 2}
    assert [(t.before, t.after, t.count) for t in summary.transitions] == [("return_to_client", "continue", 2), ("continue", "human_review", 1)]


def test_an_empty_simulation_has_no_agreement_yet() -> None:
    assert summarize([]).agreement is None
