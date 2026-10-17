"""Small transparent baselines with explicit frequency, dimensions and availability."""

import calendar
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Literal

Frequency = Literal["daily", "monthly"]
Method = Literal["last_value", "seasonal_naive", "seasonal_mean"]


class InsufficientHistory(ValueError):
    """Required observations are unavailable; no estimate is manufactured."""


@dataclass(frozen=True)
class Observation:
    """One vintage of a homogeneous daily/monthly series, never a mixed-currency pool."""

    series_id: str
    event_date: date
    published_at: datetime
    value: float
    unit: Literal["tonne", "currency/tonne"]
    currency: str | None
    revision: str
    source_url: str
    frequency: Frequency
    synthetic: bool = False

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None:
            raise ValueError("Observation availability requires a timezone")
        if self.frequency not in {"daily", "monthly"} or self.unit not in {
            "tonne",
            "currency/tonne",
        }:
            raise ValueError("Explicit supported frequency and unit required")
        if not math.isfinite(self.value) or self.value < 0:
            raise ValueError("Observation value must be finite and nonnegative")
        if self.event_date > self.published_at.astimezone(UTC).date():
            raise ValueError("Observation cannot predate its measured event")
        if self.unit == "currency/tonne" and (
            not self.currency
            or len(self.currency) != 3
            or not self.currency.isalpha()
            or not self.currency.isupper()
        ):
            raise ValueError("Price currency must be explicit")
        if self.unit == "tonne" and self.currency is not None:
            raise ValueError("Volume cannot carry a currency")
        if not self.series_id or not self.revision or not self.source_url.startswith("https://"):
            raise ValueError("Series identity, revision and source evidence required")


def snapshot(points: list[Observation], origin: datetime) -> list[Observation]:
    """Select the latest available vintage per event date within one dimensional series."""
    if origin.tzinfo is None:
        raise ValueError("Forecast origin requires timezone")
    dimensions = {(p.series_id, p.unit, p.currency, p.frequency, p.synthetic) for p in points}
    if len(dimensions) > 1:
        raise ValueError("Mixed series, units, currencies or synthetic provenance")
    cutoff = origin.astimezone(UTC)
    selected = {}
    for point in sorted(points, key=lambda p: (p.published_at, p.revision)):
        if point.published_at <= cutoff and point.event_date <= cutoff.date():
            previous = selected.get(point.event_date)
            if (
                previous
                and previous.published_at == point.published_at
                and previous.revision == point.revision
                and previous.value != point.value
            ):
                raise ValueError("Conflicting immutable observation vintage")
            selected[point.event_date] = point
    return [selected[key] for key in sorted(selected)]


def forecast_one(
    history: list[Observation], target: date, method: Method, frequency: Frequency
) -> float:
    """Daily season = weekday; monthly season = month-of-year. No interpolation."""
    if not history:
        raise InsufficientHistory("No observations available at forecast origin")
    if method not in {"last_value", "seasonal_naive", "seasonal_mean"}:
        raise ValueError("Unknown baseline")
    if frequency not in {"daily", "monthly"}:
        raise ValueError("Unknown frequency")
    if any(p.frequency != frequency for p in history):
        raise ValueError("Monthly observations cannot be used as daily data")
    history = sorted(history, key=lambda p: p.event_date)
    if target <= history[-1].event_date:
        raise ValueError("Forecast target must follow training observations")
    if frequency == "monthly" and (target.day != 1 or any(p.event_date.day != 1 for p in history)):
        raise ValueError("Monthly series require first-of-month dates")
    if method == "last_value":
        return history[-1].value
    season = lambda d: d.weekday() if frequency == "daily" else d.month
    candidates = [p.value for p in history if season(p.event_date) == season(target)]
    if method == "seasonal_mean":
        if len(candidates) < 2:
            raise InsufficientHistory("Seasonal mean needs two observed seasonal matches")
        return mean(candidates)
    reference = target
    while reference > history[-1].event_date:
        reference = (
            reference - timedelta(days=7)
            if frequency == "daily"
            else date(
                reference.year - 1,
                reference.month,
                min(reference.day, calendar.monthrange(reference.year - 1, reference.month)[1]),
            )
        )
    matches = [p.value for p in history if p.event_date == reference]
    if not matches:
        raise InsufficientHistory("Seasonal reference date is missing; no backfill")
    return matches[0]
