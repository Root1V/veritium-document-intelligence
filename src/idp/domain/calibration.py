"""Field-level accuracy and confidence calibration (VRT-43), the pure part.
A model's self-reported confidence says little on its own — measured
extractions came back 100% confident and wrong — so the confidence that
routes a field to a human is the accuracy actually observed for that
field at that confidence, from labelled observations (evaluation runs and
human reviews).

Per field ("<document_type>.<field>"), raw confidence is cut into bins;
each bin's calibrated confidence is its observed accuracy, smoothed toward
the field's accuracy when the bin has few observations (a Beta prior), and
made non-decreasing across bins (pool adjacent violators). A field with no
observations keeps its raw confidence."""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel

BIN_EDGES = (0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0)
PRIOR_WEIGHT = 5.0  # observations the field's accuracy is worth inside a bin
MIN_OBSERVATIONS = 30  # below this a field's numbers are shown as preliminary


class Observation(BaseModel):
    key: str  # "<document_type>.<field>"
    confidence: float | None
    correct: bool


class Bin(BaseModel):
    low: float
    high: float
    count: int
    accuracy: float | None
    mean_confidence: float | None
    calibrated: float


class FieldCalibration(BaseModel):
    key: str
    count: int
    accuracy: float
    mean_confidence: float | None
    ece: float | None  # expected calibration error of the raw confidence
    brier: float | None
    preliminary: bool
    bins: list[Bin]


class Calibration(BaseModel):
    fields: dict[str, FieldCalibration]

    def calibrated(self, key: str, confidence: float) -> float:
        field = self.fields.get(key)
        if field is None:
            return confidence
        return field.bins[_bin_index(confidence)].calibrated


_INDEX = re.compile(r"\[\d+\]")


def field_key(document_type: str, field_path: str) -> str:
    """List items share a key: ``concepts[2].amount`` → ``concepts[].amount``."""
    return f"{document_type}.{_INDEX.sub('[]', field_path)}"


def _bin_index(confidence: float) -> int:
    for i in range(len(BIN_EDGES) - 1):
        if confidence < BIN_EDGES[i + 1]:
            return i
    return len(BIN_EDGES) - 2  # 1.0 belongs to the last bin


def _non_decreasing(values: list[float], weights: list[float]) -> list[float]:
    """Pool adjacent violators: the closest non-decreasing sequence."""
    blocks = [[v, w, 1] for v, w in zip(values, weights, strict=True)]
    merged: list[list[float]] = []
    for block in blocks:
        merged.append(block)
        while len(merged) > 1 and merged[-2][0] > merged[-1][0]:
            v2, w2, n2 = merged.pop()
            v1, w1, n1 = merged.pop()
            w = w1 + w2
            merged.append([(v1 * w1 + v2 * w2) / w if w else (v1 + v2) / 2, w, n1 + n2])
    out: list[float] = []
    for v, _, n in merged:
        out += [v] * int(n)
    return out


def _field(key: str, observations: list[Observation]) -> FieldCalibration:
    accuracy = sum(o.correct for o in observations) / len(observations)
    scored = [(o.confidence, o.correct) for o in observations if o.confidence is not None]
    grouped: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for confidence, correct in scored:
        grouped[_bin_index(confidence)].append((confidence, correct))
    counts, accuracies, means, smoothed = [], [], [], []
    for i in range(len(BIN_EDGES) - 1):
        members = grouped.get(i, [])
        right = sum(ok for _, ok in members)
        counts.append(len(members))
        accuracies.append(right / len(members) if members else None)
        means.append(sum(c for c, _ in members) / len(members) if members else None)
        smoothed.append((right + PRIOR_WEIGHT * accuracy) / (len(members) + PRIOR_WEIGHT))
    calibrated = _non_decreasing(smoothed, [n + PRIOR_WEIGHT for n in counts])
    bins = [
        Bin(low=BIN_EDGES[i], high=BIN_EDGES[i + 1], count=counts[i], accuracy=accuracies[i], mean_confidence=means[i], calibrated=round(calibrated[i], 4))
        for i in range(len(counts))
    ]
    ece = brier = mean = None
    if scored:
        ece = round(sum(b.count * abs((b.accuracy or 0.0) - (b.mean_confidence or 0.0)) for b in bins) / len(scored), 4)
        brier = round(sum((c - ok) ** 2 for c, ok in scored) / len(scored), 4)
        mean = round(sum(c for c, _ in scored) / len(scored), 4)
    return FieldCalibration(
        key=key,
        count=len(observations),
        accuracy=round(accuracy, 4),
        mean_confidence=mean,
        ece=ece,
        brier=brier,
        preliminary=len(observations) < MIN_OBSERVATIONS,
        bins=bins,
    )


def calibrate(observations: list[Observation]) -> Calibration:
    by_key: dict[str, list[Observation]] = defaultdict(list)
    for o in observations:
        by_key[o.key].append(o)
    return Calibration(fields={key: _field(key, obs) for key, obs in sorted(by_key.items())})


class ThresholdSuggestion(BaseModel):
    target_error: float
    threshold: float | None  # None: no threshold reaches the target
    coverage: float  # share of fields that would pass without a human
    error_rate: float | None  # observed error among those that pass


def suggest_threshold(calibration: Calibration, observations: list[Observation], *, target_error: float) -> ThresholdSuggestion:
    """The lowest calibrated-confidence threshold whose auto-accepted
    fields (at or above it) err no more than ``target_error`` — the most
    automation that keeps the error rate."""
    scored = [(calibration.calibrated(o.key, o.confidence), o.correct) for o in observations if o.confidence is not None]
    if not scored:
        return ThresholdSuggestion(target_error=target_error, threshold=None, coverage=0.0, error_rate=None)
    for threshold in sorted({c for c, _ in scored}):
        passing = [ok for c, ok in scored if c >= threshold]
        error = 1 - sum(passing) / len(passing)
        if error <= target_error:
            return ThresholdSuggestion(
                target_error=target_error, threshold=round(threshold, 4), coverage=round(len(passing) / len(scored), 4), error_rate=round(error, 4)
            )
    return ThresholdSuggestion(target_error=target_error, threshold=None, coverage=0.0, error_rate=None)
