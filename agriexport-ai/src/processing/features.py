"""Point-in-time weather/event feature selection; feeds and LLM extraction remain separate."""

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WeatherFeature:
    """A source forecast known at a run/publication time, valid at a different time."""

    country_code: str
    region: str
    variable: str
    value: float
    unit: str
    forecast_run_at: datetime
    valid_at: datetime
    published_at: datetime
    source_url: str
    verified: bool

    def __post_init__(self) -> None:
        if any(t.tzinfo is None for t in (self.forecast_run_at, self.valid_at, self.published_at)):
            raise ValueError("Weather timestamps require timezone")
        if (
            not math.isfinite(self.value)
            or not self.unit
            or not self.source_url.startswith("https://")
        ):
            raise ValueError("Weather value/unit/source invalid")
        if self.forecast_run_at > self.published_at:
            raise ValueError("Weather run cannot be available before it is issued")


def weather_as_of(
    points: list[WeatherFeature], origin: datetime, country_code: str, valid_until: datetime
) -> list[WeatherFeature]:
    """Select latest verified run per variable/region/valid time without future-run leakage."""
    if origin.tzinfo is None or valid_until.tzinfo is None or valid_until < origin:
        raise ValueError("Valid timezone-aware feature window required")
    selected = {}
    for point in sorted(points, key=lambda p: (p.forecast_run_at, p.published_at)):
        if (
            point.verified
            and point.country_code == country_code
            and point.forecast_run_at <= origin
            and point.published_at <= origin
            and origin <= point.valid_at <= valid_until
        ):
            selected[(point.region, point.variable, point.valid_at, point.unit)] = point
    return list(selected.values())


@dataclass(frozen=True)
class EventFeature:
    """Verified structured text event; extraction confidence is not forecast confidence."""

    product_id: str
    country_code: str
    event_date: datetime
    published_at: datetime
    expiry_date: datetime
    impact_direction: str
    extraction_confidence: float
    source_url: str
    verified: bool

    def __post_init__(self) -> None:
        if any(t.tzinfo is None for t in (self.event_date, self.published_at, self.expiry_date)):
            raise ValueError("Event timestamps require timezone")
        if (
            self.expiry_date < self.published_at
            or self.impact_direction not in {"increase", "decrease", "uncertain"}
            or not math.isfinite(self.extraction_confidence)
            or not 0 <= self.extraction_confidence <= 1
            or not self.source_url.startswith("https://")
        ):
            raise ValueError("Invalid structured event/evidence")


def events_as_of(
    events: list[EventFeature],
    origin: datetime,
    product_id: str,
    country_code: str,
    valid_until: datetime,
) -> list[EventFeature]:
    """Deduplicate active known events by source/product/country/event date."""
    if origin.tzinfo is None or valid_until.tzinfo is None or valid_until < origin:
        raise ValueError("Valid timezone-aware feature window required")
    selected = {}
    for event in sorted(events, key=lambda e: e.published_at):
        if (
            event.verified
            and event.product_id == product_id
            and event.country_code == country_code
            and event.published_at <= origin
            and event.expiry_date >= origin
            and event.event_date <= valid_until
        ):
            selected[(event.source_url, event.product_id, event.country_code, event.event_date)] = (
                event
            )
    return list(selected.values())
