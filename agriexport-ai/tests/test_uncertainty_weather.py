"""SYNTHETIC residuals and weather payloads; not calibration of a live model."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from src.forecasting.uncertainty import CalibrationResidual, calibrated_interval, interval_coverage
from src.ingestion.weather import NasaPowerConnector

ORIGIN = datetime(2025, 5, 1, tzinfo=UTC)


def residuals() -> list[CalibrationResidual]:
    return [
        CalibrationResidual(
            "SYNTHETIC",
            "SYNTHETIC-v1",
            7,
            ORIGIN - timedelta(days=60 + i),
            ORIGIN - timedelta(days=53 + i),
            ORIGIN - timedelta(days=50 + i),
            float(i),
            True,
        )
        for i in range(30)
    ]


def test_intervals_need_known_homogeneous_calibration_and_enough_samples():
    assert calibrated_interval(100, residuals()[:3], ORIGIN) is None
    result = calibrated_interval(100, residuals(), ORIGIN)
    assert result["synthetic"] and result["lower"] == 73 and result["upper"] == 127
    assert interval_coverage([80, 140], [(73, 127), (73, 127)]) == 0.5
    assert interval_coverage([], []) is None
    with pytest.raises(ValueError, match="leakage"):
        calibrated_interval(
            100, [replace(residuals()[0], label_published_at=ORIGIN + timedelta(days=1))], ORIGIN
        )
    with pytest.raises(ValueError, match="horizon"):
        calibrated_interval(100, residuals() + [replace(residuals()[0], horizon_days=14)], ORIGIN)


def synthetic_nasa(fill: bool = False) -> dict:
    return {
        "synthetic": True,
        "header": {"time_standard": "UTC", "fill_value": -999},
        "parameters": {"T2M": {"units": "C"}, "PRECTOTCORR": {"units": "mm/day"}},
        "properties": {
            "parameter": {
                "T2M": {"20250101": -999 if fill else 20.0},
                "PRECTOTCORR": {"20250101": 1.0},
            }
        },
    }


def test_nasa_transport_cache_units_and_first_observed_availability(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=synthetic_nasa())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        connector = NasaPowerConnector(client, tmp_path, synthetic=True)
        first = connector.fetch(0, 0, date(2025, 1, 1), date(2025, 1, 1))
        second = connector.fetch(0, 0, date(2025, 1, 1), date(2025, 1, 1))
    assert len(calls) == 1 and first["published_at"] == second["published_at"]
    assert first["published_at"] == first["retrieved_at"]
    assert first["synthetic"] and len(first["measurements"]) == 2
    assert first["forecast_run_at"] is None


def test_missing_weather_is_not_zero(tmp_path):
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=synthetic_nasa(True)))
        ) as client,
        pytest.raises(ValueError, match="missing"),
    ):
        NasaPowerConnector(client, tmp_path, synthetic=True).fetch(
            0, 0, date(2025, 1, 1), date(2025, 1, 1)
        )
    manifest = json.loads((tmp_path / "retrievals.jsonl").read_text().splitlines()[0])
    assert manifest["synthetic"]
