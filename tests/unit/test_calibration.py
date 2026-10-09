"""Unit tests for VRT-43: calibrated confidence per field, its metrics, the
suggested threshold, and review routing with a calibration."""

from __future__ import annotations

from idp.domain.calibration import Calibration, Observation, calibrate, field_key, suggest_threshold
from idp.domain.envelope import Extracted
from idp.domain.schemas.payslip import PayslipSchema
from idp.review.routing import find_review_candidates


def _obs(key: str, confidence: float, right: int, wrong: int) -> list[Observation]:
    return [Observation(key=key, confidence=confidence, correct=True)] * right + [Observation(key=key, confidence=confidence, correct=False)] * wrong


def test_an_overconfident_field_is_calibrated_down_to_its_observed_accuracy() -> None:
    # employee_code says 100% and is right 6 times out of 10.
    model = calibrate(_obs("payslip.employee_code", 1.0, right=6, wrong=4))
    field = model.fields["payslip.employee_code"]
    assert field.accuracy == 0.6
    assert field.ece == 0.4, "said 1.0, was right 0.6 of the time"
    assert model.calibrated("payslip.employee_code", 1.0) == 0.6
    assert field.preliminary, "10 observations are not enough to trust"


def test_a_field_without_observations_keeps_its_raw_confidence() -> None:
    model = calibrate(_obs("payslip.net_pay", 0.9, right=5, wrong=0))
    assert model.calibrated("payslip.period", 0.42) == 0.42


def test_a_sparse_bin_leans_on_the_field_accuracy_and_bins_never_decrease() -> None:
    observations = _obs("t.f", 0.95, right=1, wrong=1) + _obs("t.f", 0.6, right=18, wrong=2)
    model = calibrate(observations)
    bins = model.fields["t.f"].bins
    # the 0.95 bin saw 1/2 right: alone it would say 0.5, below the 0.6 bin's 0.9
    assert bins[5].accuracy == 0.5
    assert all(a.calibrated <= b.calibrated for a, b in zip(bins, bins[1:], strict=False))


def test_the_suggested_threshold_keeps_the_target_error_with_the_most_automation() -> None:
    observations = _obs("t.good", 0.9, right=99, wrong=1) + _obs("t.bad", 1.0, right=7, wrong=3)
    model = calibrate(observations)
    suggestion = suggest_threshold(model, observations, target_error=0.02)
    assert suggestion.threshold is not None and suggestion.threshold > model.calibrated("t.bad", 1.0)
    assert suggestion.coverage == round(100 / 110, 4), "the good field passes alone; the bad one goes to a human"
    assert suggestion.error_rate == 0.01


def test_list_items_share_a_key() -> None:
    assert field_key("payslip", "concepts[2].amount") == "payslip.concepts[].amount"


def test_routing_with_a_calibration_sends_an_overconfident_field_to_review() -> None:
    def e(value: object) -> Extracted:
        return Extracted(value=value, page=0, confidence=1.0)

    payslip = PayslipSchema(
        employee_name=e("ANA"), employee_code=e("011858"), period=e("01/2026"), gross_pay=e(1000.0), total_deductions=e(200.0), net_pay=e(800.0)
    )
    model: Calibration = calibrate(_obs("payslip.employee_code", 1.0, right=6, wrong=4))
    assert find_review_candidates(payslip, [], confidence_threshold=0.85) == []
    flagged = find_review_candidates(
        payslip, [], confidence_threshold=0.85, calibrate=lambda path, raw: model.calibrated(field_key("payslip", path), raw)
    )
    assert [c.field_path for c in flagged] == ["employee_code"]
