"""Finite-sample conformal intervals from genuinely known calibration residuals only."""

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CalibrationResidual:
    """A forecast frozen before its outcome, and the later availability of its residual."""

    series_id: str
    model_version: str
    horizon_days: int
    forecast_origin: datetime
    target_end: datetime
    label_published_at: datetime
    absolute_error: float
    synthetic: bool

    def __post_init__(self) -> None:
        if any(
            t.tzinfo is None
            for t in (self.forecast_origin, self.target_end, self.label_published_at)
        ):
            raise ValueError("Calibration timestamps require timezone")
        if not self.forecast_origin < self.target_end <= self.label_published_at:
            raise ValueError("Calibration target/availability order invalid")
        if (
            self.horizon_days not in {7, 14, 28}
            or not math.isfinite(self.absolute_error)
            or self.absolute_error < 0
        ):
            raise ValueError("Calibration horizon/error invalid")


def calibrated_interval(
    prediction: float,
    residuals: list[CalibrationResidual],
    origin: datetime,
    coverage: float = 0.9,
    min_samples: int = 20,
) -> dict | None:
    """Return a nominal conformal interval, not a calibrated success probability.

    Unknown residuals and mixed horizons/models/provenance raise rather than leak.
    No interval is available when the conservative finite-sample quantile is unbounded.
    """
    if (
        origin.tzinfo is None
        or not math.isfinite(prediction)
        or prediction < 0
        or not 0 < coverage < 1
        or min_samples < 1
    ):
        raise ValueError("Invalid interval parameters")
    if len({(r.series_id, r.model_version, r.horizon_days, r.synthetic) for r in residuals}) > 1:
        raise ValueError("Calibration series/model/horizon/provenance must match")
    if any(r.label_published_at > origin or r.target_end >= origin for r in residuals):
        raise ValueError("Future outcome leakage in interval calibration")
    rank = math.ceil((len(residuals) + 1) * coverage)
    if len(residuals) < min_samples or rank > len(residuals):
        return None
    radius = sorted(r.absolute_error for r in residuals)[rank - 1]
    return {
        "lower": max(0, prediction - radius),
        "upper": prediction + radius,
        "nominal_coverage": coverage,
        "calibration_n": len(residuals),
        "method": "split_conformal_absolute_error",
        "synthetic": residuals[0].synthetic,
    }


def interval_coverage(actual: list[float], bounds: list[tuple[float, float]]) -> float | None:
    """Measure empirical held-out coverage; an empty evaluation is undefined."""
    if len(actual) != len(bounds):
        raise ValueError("Interval/actual lengths differ")
    if any(
        not all(math.isfinite(v) for v in (a, lo, hi)) or lo > hi
        for a, (lo, hi) in zip(actual, bounds, strict=True)
    ):
        raise ValueError("Invalid prediction interval")
    return (
        sum(lo <= a <= hi for a, (lo, hi) in zip(actual, bounds, strict=True)) / len(actual)
        if actual
        else None
    )
