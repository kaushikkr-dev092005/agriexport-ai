"""Window demand baselines require daily observations; monthly history remains context."""

from datetime import UTC, datetime, timedelta

from src.forecasting.baselines import (
    InsufficientHistory,
    Method,
    Observation,
    forecast_one,
    snapshot,
)
from src.forecasting.config import BaselineSettings


def predict_demand(
    points: list[Observation],
    origin: datetime,
    horizon_days: int,
    method: Method = "last_value",
    settings: BaselineSettings | None = None,
) -> float:
    """Forecast total demand over the next 7/14/28 days from daily tonne observations."""
    if horizon_days not in {7, 14, 28}:
        raise ValueError("Horizon must be 7, 14 or 28 days")
    history = snapshot(points, origin)
    settings = settings or BaselineSettings()
    origin = origin.astimezone(UTC)
    if any(p.unit != "tonne" or p.frequency != "daily" for p in history):
        raise ValueError("Demand requires tonnes, never trade value or a price")
    if history and (origin.date() - history[-1].event_date).days > settings.max_daily_data_age_days:
        raise InsufficientHistory("Daily demand history is stale")
    # Caller must pass genuinely daily data; the published API only uses monthly context.
    return sum(
        forecast_one(history, origin.date() + timedelta(days=day), method, "daily")
        for day in range(1, horizon_days + 1)
    )
