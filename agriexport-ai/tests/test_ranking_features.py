"""SYNTHETIC rules, score components and weather/events; no real policy claims."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.policy_checks import (
    Eligibility,
    GateCategory,
    PolicyEvidence,
    check_eligibility,
)
from src.processing.features import EventFeature, WeatherFeature, events_as_of, weather_as_of
from src.ranking.opportunity_score import load_weights, score_opportunity

ORIGIN = datetime(2025, 3, 1, tzinfo=UTC)


def synthetic_policies() -> list[PolicyEvidence]:
    return [
        PolicyEvidence(
            category,
            "rice",
            "682",
            "ALLOW",
            ORIGIN - timedelta(days=10),
            ORIGIN - timedelta(days=9),
            ORIGIN - timedelta(days=10),
            ORIGIN + timedelta(days=60),
            "https://example.org/SYNTHETIC/policy",
        )
        for category in GateCategory
    ]


def test_all_categories_required_and_ban_overrides_score():
    assert check_eligibility(synthetic_policies(), "rice", "682", ORIGIN, 28).eligible
    assert not check_eligibility(synthetic_policies()[:-1], "rice", "682", ORIGIN, 7).eligible
    future_ban = replace(
        synthetic_policies()[0], decision="BLOCK", effective_from=ORIGIN + timedelta(days=10)
    )
    assert check_eligibility(synthetic_policies() + [future_ban], "rice", "682", ORIGIN, 7).eligible
    gate = check_eligibility(synthetic_policies() + [future_ban], "rice", "682", ORIGIN, 14)
    assert not gate.eligible
    assert score_opportunity(gate, None)["score"] is None
    unknown = replace(synthetic_policies()[0], decision="UNVERIFIED", verified_at=None)
    assert not check_eligibility(
        synthetic_policies() + [unknown], "rice", "682", ORIGIN, 7
    ).eligible


@pytest.mark.parametrize("bad", [-1, 101, float("nan"), float("inf"), True])
def test_score_rejects_invalid_ranges(bad):
    components = dict.fromkeys(load_weights(), 50)
    components["profit"] = bad
    with pytest.raises(ValueError):
        score_opportunity(Eligibility(True, ()), components)


def test_score_formula_missing_inputs_and_blocked_gate_first():
    components = {
        "demand": 80,
        "indian_supply": 60,
        "profit": 50,
        "accessibility": 100,
        "confidence": 90,
    }
    assert score_opportunity(Eligibility(True, ()), components)["score"] == pytest.approx(71)
    assert score_opportunity(Eligibility(True, ()), None)["score"] is None
    assert (
        score_opportunity(Eligibility(False, ("SYNTHETIC unknown",)), {"profit": 1000})["score"]
        is None
    )


def test_weather_runs_and_events_cannot_leak_future_publication():
    point = WeatherFeature(
        "682",
        "SYNTHETIC-region",
        "rainfall",
        1,
        "mm",
        ORIGIN - timedelta(hours=1),
        ORIGIN + timedelta(days=1),
        ORIGIN - timedelta(minutes=30),
        "https://example.org/SYNTHETIC",
        True,
    )
    later = replace(
        point,
        value=999,
        forecast_run_at=ORIGIN + timedelta(hours=1),
        published_at=ORIGIN + timedelta(hours=2),
    )
    assert weather_as_of([point, later], ORIGIN, "682", ORIGIN + timedelta(days=7)) == [point]
    event = EventFeature(
        "rice",
        "682",
        ORIGIN,
        ORIGIN - timedelta(hours=1),
        ORIGIN + timedelta(days=7),
        "increase",
        0.8,
        "https://example.org/SYNTHETIC/event",
        True,
    )
    future = replace(event, published_at=ORIGIN + timedelta(days=1))
    assert events_as_of([event, future], ORIGIN, "rice", "682", ORIGIN + timedelta(days=7)) == [
        event
    ]
    assert (
        events_as_of(
            [replace(event, verified=False)], ORIGIN, "rice", "682", ORIGIN + timedelta(days=7)
        )
        == []
    )
