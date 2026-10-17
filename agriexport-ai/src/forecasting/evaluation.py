"""Chronological backtests: origin snapshots for features, later snapshots for labels."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Literal

from src.forecasting.baselines import InsufficientHistory, Method, Observation, snapshot
from src.forecasting.config import BaselineSettings, load_settings
from src.forecasting.demand import predict_demand
from src.forecasting.price import predict_price


@dataclass(frozen=True)
class BacktestRow:
    """One pre-outcome forecast paired with fully observed out-of-time truth."""

    origin: datetime
    horizon_days: int
    method: Method
    actual: float
    predicted: float
    synthetic: bool
    training_snapshot_hash: str
    training_n: int


def regression_metrics(actual: list[float], predicted: list[float]) -> dict:
    """Report MAE/WAPE/bias; undefined empty/all-zero denominators remain null."""
    if len(actual) != len(predicted):
        raise ValueError("Actual and prediction lengths differ")
    if not all(math.isfinite(x) for x in actual + predicted):
        raise ValueError("Metrics require finite values")
    if not actual:
        return {"n": 0, "mae": None, "wape": None, "bias": None}
    error = [p - a for a, p in zip(actual, predicted, strict=True)]
    denominator = sum(abs(a) for a in actual)
    return {
        "n": len(actual),
        "mae": mean(abs(e) for e in error),
        "wape": sum(abs(e) for e in error) / denominator if denominator else None,
        "bias": mean(error),
    }


def backtest(
    points: list[Observation],
    origins: list[datetime],
    evaluation_cutoff: datetime,
    target: Literal["demand", "price"] = "demand",
    min_history: int | None = None,
    settings: BaselineSettings | None = None,
) -> dict:
    """Evaluate all horizons/methods separately; skip folds with missing labels or history.

    Demand truth is a complete future 7/14/28-day sum. Price truth is the endpoint.
    Evaluation truth vintages are frozen at evaluation_cutoff; training at each origin.
    """
    settings = settings or load_settings()
    min_history = (
        min_history if min_history is not None else settings.daily_min_history_observations
    )
    if evaluation_cutoff.tzinfo is None:
        raise ValueError("Evaluation cutoff requires timezone")
    if target not in {"demand", "price"} or min_history < 1:
        raise ValueError("Invalid evaluation target or history requirement")
    if any(p.frequency != "daily" for p in points):
        raise ValueError("7/14/28-day backtests require daily labels, not monthly trade")
    if any(o.tzinfo is None for o in origins) or origins != sorted(set(origins)):
        raise ValueError("Unique chronological timezone-aware origins required")
    truth = {p.event_date: p for p in snapshot(points, evaluation_cutoff)}
    results, skipped = [], []
    for origin in origins:
        origin = origin.astimezone(UTC)
        if origin >= evaluation_cutoff:
            raise ValueError("Origin must precede evaluation cutoff")
        history = snapshot(points, origin)
        training_hash = hashlib.sha256(
            json.dumps(
                [
                    [
                        p.series_id,
                        p.event_date.isoformat(),
                        p.published_at.isoformat(),
                        p.value,
                        p.unit,
                        p.currency,
                        p.revision,
                        p.source_url,
                        p.frequency,
                        p.synthetic,
                    ]
                    for p in history
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for horizon in settings.horizons_days:
            dates = [
                origin.date() + timedelta(days=d)
                for d in (range(1, horizon + 1) if target == "demand" else [horizon])
            ]
            if len(history) < min_history or any(day not in truth for day in dates):
                skipped.append(
                    {
                        "origin": origin.isoformat(),
                        "horizon_days": horizon,
                        "reason": "insufficient_available_history_or_future_labels",
                    }
                )
                continue
            actual = sum(truth[d].value for d in dates)
            for method in settings.methods:
                try:
                    prediction = (predict_demand if target == "demand" else predict_price)(
                        history, origin, horizon, method, settings
                    )
                except InsufficientHistory as error:
                    skipped.append(
                        {
                            "origin": origin.isoformat(),
                            "horizon_days": horizon,
                            "method": method,
                            "reason": str(error),
                        }
                    )
                    continue
                results.append(
                    BacktestRow(
                        origin,
                        horizon,
                        method,
                        actual,
                        prediction,
                        any(p.synthetic for p in history),
                        training_hash,
                        len(history),
                    )
                )
    segments = []
    for horizon in (7, 14, 28):
        for method in ("last_value", "seasonal_naive", "seasonal_mean"):
            rows = [r for r in results if r.horizon_days == horizon and r.method == method]
            segments.append(
                {
                    "horizon_days": horizon,
                    "method": method,
                    **regression_metrics([r.actual for r in rows], [r.predicted for r in rows]),
                }
            )
    return {
        "status": "NOT_CALCULATED"
        if not results
        else "EVALUATED_SYNTHETIC"
        if any(p.synthetic for p in points)
        else "EVALUATED_BASELINES",
        "ml_value_claim": "not_established",
        "target": target,
        "segments": segments,
        "skipped": skipped,
        "synthetic": any(p.synthetic for p in points),
        "label": "SYNTHETIC — NOT MEASURED LIVE PERFORMANCE"
        if any(p.synthetic for p in points)
        else "Historical evaluation; baseline performance only",
        "evaluation_cutoff": evaluation_cutoff.isoformat(),
        "configuration": settings.model_dump(mode="json"),
        "predictions": [
            {
                "origin": r.origin.isoformat(),
                "horizon_days": r.horizon_days,
                "method": r.method,
                "actual": r.actual,
                "predicted": r.predicted,
                "synthetic": r.synthetic,
                "training_snapshot_hash": r.training_snapshot_hash,
                "training_n": r.training_n,
            }
            for r in results
        ],
    }
