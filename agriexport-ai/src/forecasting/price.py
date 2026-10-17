"""Price baselines apply to quoted/observed prices, never customs unit values."""

from datetime import UTC, datetime, timedelta

from src.forecasting.baselines import (
    InsufficientHistory,
    Method,
    Observation,
    forecast_one,
    snapshot,
)
from src.forecasting.config import BaselineSettings


def predict_price(
    points: list[Observation],
    origin: datetime,
    horizon_days: int,
    method: Method = "last_value",
    settings: BaselineSettings | None = None,
) -> float:
    """Forecast the endpoint price in the same explicit currency per tonne."""
    if horizon_days not in {7, 14, 28}:
        raise ValueError("Horizon must be 7, 14 or 28 days")
    history = snapshot(points, origin)
    settings = settings or BaselineSettings()
    origin = origin.astimezone(UTC)
    if any(p.unit != "currency/tonne" or p.frequency != "daily" for p in history):
        raise ValueError("Price baseline requires a price series with explicit currency")
    if history and (origin.date() - history[-1].event_date).days > settings.max_daily_data_age_days:
        raise InsufficientHistory("Daily price history is stale")
    return forecast_one(history, origin.date() + timedelta(days=horizon_days), method, "daily")
