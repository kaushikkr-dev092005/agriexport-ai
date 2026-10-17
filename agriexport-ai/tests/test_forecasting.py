"""SYNTHETIC quantitative fixtures; measured synthetic tests are never live ML performance."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.main import create_app
from src.database.repository import ingest, init_local, make_engine
from src.forecasting.baselines import Observation, snapshot
from src.forecasting.demand import predict_demand
from src.forecasting.evaluation import backtest, regression_metrics
from src.forecasting.price import predict_price
from src.forecasting.service import latest_forecasts, run_forecasts
from tests.test_foundation import NOW, synthetic_row


def daily_series(price: bool = False) -> list[Observation]:
    """SYNTHETIC complete daily pattern, published the next day after measurement."""
    output = []
    for offset in range(150):
        day = date(2025, 1, 1) + timedelta(days=offset)
        value = 100 + day.weekday() if price else 1 + day.weekday()
        output.append(
            Observation(
                "SYNTHETIC-price" if price else "SYNTHETIC-demand",
                day,
                datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC),
                value,
                "currency/tonne" if price else "tonne",
                "USD" if price else None,
                "SYNTHETIC-v1",
                "https://example.org/SYNTHETIC",
                "daily",
                True,
            )
        )
    return output


@pytest.mark.parametrize("horizon", [7, 14, 28])
def test_demand_forecasts_window_sum_and_price_endpoint(horizon):
    origin = datetime(2025, 3, 1, tzinfo=UTC)
    assert predict_demand(daily_series(), origin, horizon, "seasonal_naive") == horizon * 4
    assert predict_demand(daily_series(), origin, horizon, "seasonal_mean") == horizon * 4
    assert predict_price(daily_series(True), origin, horizon, "seasonal_naive") == 105


def test_monthly_never_used_as_daily_or_price():
    point = replace(daily_series()[0], frequency="monthly")
    with pytest.raises(ValueError):
        predict_demand([point], NOW, 7)
    with pytest.raises(ValueError):
        predict_price(daily_series(), NOW, 7)
    with pytest.raises(ValueError):
        backtest([point], [NOW], NOW + timedelta(days=40))
    with pytest.raises(ValueError):
        snapshot(
            [daily_series()[0], replace(daily_series()[1], unit="currency/tonne", currency="USD")],
            NOW,
        )


def test_point_in_time_revisions_exclude_future_information():
    points = daily_series()
    origin = datetime(2025, 3, 1, tzinfo=UTC)
    history = snapshot(points, origin)
    recent = history[-1]
    future_revision = replace(
        recent, value=99999, revision="SYNTHETIC-v2", published_at=origin + timedelta(days=60)
    )
    assert predict_demand(points + [future_revision], origin, 7) == predict_demand(
        points, origin, 7
    )
    assert snapshot(points + [future_revision], origin)[-1].value == recent.value


def test_chronological_backtest_compares_all_horizons_and_baselines():
    origin = datetime(2025, 3, 1, tzinfo=UTC)
    report = backtest(
        daily_series(), [origin, origin + timedelta(days=7)], datetime(2025, 6, 1, tzinfo=UTC)
    )
    assert report["synthetic"] and report["label"].startswith("SYNTHETIC")
    assert len(report["segments"]) == 9
    assert all(r["n"] == 2 for r in report["segments"])
    assert all(r["mae"] == 0 for r in report["segments"] if r["method"] == "seasonal_naive")
    with pytest.raises(ValueError):
        backtest(daily_series(), [origin, origin - timedelta(days=1)], origin + timedelta(days=40))


def test_history_retrieved_late_does_not_enable_historical_backtest():
    points = [replace(p, published_at=datetime(2026, 1, 1, tzinfo=UTC)) for p in daily_series()]
    report = backtest(points, [datetime(2025, 3, 1, tzinfo=UTC)], datetime(2026, 2, 1, tzinfo=UTC))
    assert all(r["n"] == 0 and r["mae"] is None for r in report["segments"])


def test_metrics_are_defined_honestly():
    result = regression_metrics([10, 20], [12, 18])
    assert result["mae"] == 2 and result["wape"] == pytest.approx(4 / 30) and result["bias"] == 0
    assert regression_metrics([], [])["mae"] is None
    assert regression_metrics([0], [1])["wape"] is None
    with pytest.raises(ValueError):
        regression_metrics([float("nan")], [1])


def test_persisted_context_idempotency_and_no_backdated_live_run(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'context.db'}")
    init_local(engine)
    with Session(engine) as session, session.begin():
        ingest(session, [synthetic_row()], "SYNTHETIC.raw")
        assert run_forecasts(session, datetime(2025, 2, 9, tzinfo=UTC), True) == []
        runs = run_forecasts(session, NOW, True)
        assert len(runs) == 3 and {p.horizon_days for p in runs} == {7, 14, 28}
        assert all(
            p.demand_forecast is None and p.payload["opportunity_score"] is None for p in runs
        )
        assert [p.prediction_id for p in run_forecasts(session, NOW, True)] == [
            p.prediction_id for p in runs
        ]
        assert latest_forecasts(session, NOW, include_synthetic=True) == []
        assert latest_forecasts(session, datetime.now(UTC)) == []
    client = TestClient(create_app(engine))
    forecasts = client.get("/api/v1/forecasts?include_synthetic=true").json()
    assert len(forecasts) == 3 and all(p["label"].startswith("SYNTHETIC") for p in forecasts)
    assert client.get("/api/v1/forecasts?horizon_days=8").status_code == 422
    assert client.get("/api/v1/forecasts?as_of=2025-03-01").status_code == 422
    engine.dispose()


def test_monthly_baselines_group_period_urls_and_never_create_weekly_totals():
    import calendar
    from decimal import Decimal

    from src.database.models import TradeObservation
    from src.forecasting.service import monthly_context

    rows = []
    for offset in range(14):
        month = date(2024 + offset // 12, 1 + offset % 12, 1)
        rows.append(
            TradeObservation(
                observation_id=f"{offset:064x}",
                product_id="rice",
                reporter="156",
                partner="000",
                period=month,
                event_date=month.replace(day=calendar.monthrange(month.year, month.month)[1]),
                flow="M",
                quantity=Decimal(2),
                unit="tonne",
                value=Decimal(1),
                currency="USD",
                published_at=NOW,
                retrieved_at=NOW,
                revision="SYNTHETIC-v1",
                source_url=f"https://example.org/SYNTHETIC?period={month.isoformat()}",
                raw_sha256="a" * 64,
                availability_basis="first_observed",
                synthetic=True,
            )
        )
    context = monthly_context(rows, "156", NOW)
    assert len(context) == 3
    naive = next(c for c in context if c["method"] == "seasonal_naive")
    assert naive["monthly_quantity_tonnes"] == 2 and naive["target_month"] == "2025-03-01"


def test_stale_series_requires_explicit_config_change():
    from src.forecasting.baselines import InsufficientHistory
    from src.forecasting.config import BaselineSettings

    points = daily_series()[:30]
    with pytest.raises(InsufficientHistory, match="stale"):
        predict_demand(points, NOW, 7)
    assert predict_demand(points, NOW, 7, settings=BaselineSettings(max_daily_data_age_days=90)) > 0
