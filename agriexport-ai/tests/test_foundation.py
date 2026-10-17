"""All numeric fixtures in this file are SYNTHETIC, never live trade signals."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from apps.api.main import create_app
from src.database.repository import ingest, init_local, make_engine, snapshot
from src.ingestion.apeda import load_indian_csv
from src.ingestion.comtrade import ComtradeConnector, normalize
from src.processing.hs_mapping import validate_mapping
from src.processing.validation import TradeRow

NOW = datetime(2025, 3, 1, tzinfo=UTC)


def synthetic_row(**changes) -> TradeRow:
    """Explicit SYNTHETIC fixture with traceable availability semantics."""
    values = {
        "product_id": "rice",
        "hs_code": "1006",
        "hs_revision": "HS2022",
        "reporter": "356",
        "partner": "682",
        "period": "2025-01-01",
        "event_date": "2025-01-31",
        "flow": "X",
        "quantity": "2000",
        "quantity_unit": "kg",
        "value": "1000",
        "currency": "USD",
        "published_at": "2025-02-10T00:00:00Z",
        "retrieved_at": NOW,
        "availability_basis": "source_publication",
        "publication_evidence_url": "https://example.org/SYNTHETIC/publication",
        "source_url": "https://example.org/SYNTHETIC/trade",
        "raw_sha256": "a" * 64,
        "revision": "SYNTHETIC-v1",
        "synthetic": True,
    }
    values.update(changes)
    return TradeRow(**values)


@pytest.fixture
def engine(tmp_path):
    """Use a file DB so API threads see the same disposable database."""
    db = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_local(db)
    yield db
    db.dispose()


def test_units_and_currencies():
    assert synthetic_row().quantity_tonnes == Decimal(2)
    assert synthetic_row(quantity_unit="tonne").quantity_tonnes == Decimal(2000)
    assert synthetic_row(currency="INR").value == Decimal(1000)  # No implicit FX.


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity_unit": "quintal"},
        {"currency": "rupees"},
        {"quantity": -1},
        {"quantity": "NaN"},
        {"value": "Infinity"},
        {"published_at": "2025-02-10"},
        {"publication_evidence_url": None},
        {"period": "2025-01-31"},
        {"event_date": "2025-02-28"},
        {"availability_basis": "first_observed"},
        {"source_url": "unknown"},
        {"published_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_ambiguous_or_leaking_data_rejected(changes):
    with pytest.raises(ValidationError):
        synthetic_row(**changes)


def test_mapping_no_guessed_detail():
    validate_mapping("rice", "1006", "HS2022")
    for product, code, revision in [
        ("rice", "10063020", "HS2022"),
        ("tea", "1006", "HS2022"),
        ("rice", "1006", "HS2017"),
    ]:
        with pytest.raises(ValueError):
            validate_mapping(product, code, revision)


def test_catalogue_has_official_edition_evidence():
    """Reject catalogue expansion without the recorded HS2022 source review."""
    from pathlib import Path

    from src.processing.hs_mapping import catalogue

    evidence = json.loads(Path("configs/catalogue_verification.json").read_text())
    assert evidence["edition"] == "HS2022"
    assert set(evidence["codes_verified"]) == {
        p["hs_code"] for p in catalogue() if p["hs_revision"] == "HS2022"
    }
    assert all(
        p["source_url"] == evidence["source_url"]
        for p in catalogue()
        if p["hs_revision"] == "HS2022"
    )
    assert all(p["itc_hs_status"] == "unverified" for p in catalogue())


def test_point_in_time_revision_and_idempotency(engine):
    with Session(engine) as session, session.begin():
        assert ingest(session, [synthetic_row()], "SYNTHETIC.raw") == 1
        assert ingest(session, [synthetic_row()], "SYNTHETIC.raw") == 0
        revised = synthetic_row(
            quantity="3000", revision="SYNTHETIC-v2", published_at="2025-02-20T00:00:00Z"
        )
        ingest(session, [revised], "SYNTHETIC.raw")
        assert snapshot(session, datetime(2025, 2, 9, tzinfo=UTC), include_synthetic=True) == []
        earlier = snapshot(session, datetime(2025, 2, 15, tzinfo=UTC), include_synthetic=True)
        assert len(earlier) == 1 and earlier[0].quantity == Decimal(2)
        latest = snapshot(session, NOW, include_synthetic=True)
        assert len(latest) == 1 and latest[0].quantity == Decimal(3)
        assert snapshot(session, NOW) == []  # Synthetic is opt-in.
        with pytest.raises(ValueError, match="Conflicting"):
            ingest(session, [synthetic_row(quantity="9999")], "SYNTHETIC.raw")


def test_timezone_offsets_do_not_shift_availability(engine):
    """Same instant in different zones yields identical training snapshots."""
    row = synthetic_row(published_at="2025-02-10T05:30:00+05:30")
    assert row.published_at.isoformat() == "2025-02-10T00:00:00+00:00"
    with Session(engine) as session, session.begin():
        ingest(session, [row], "SYNTHETIC.raw")
        before = datetime.fromisoformat("2025-02-10T05:29:00+05:30")
        after = datetime.fromisoformat("2025-02-10T05:31:00+05:30")
        assert snapshot(session, before, include_synthetic=True) == []
        assert len(snapshot(session, after, include_synthetic=True)) == 1


def test_batch_rejects_unknown_mapping_before_any_writes(engine):
    from sqlalchemy import func, select

    from src.database.models import TradeObservation

    with Session(engine) as session, session.begin():
        with pytest.raises(ValueError, match="mapping"):
            ingest(session, [synthetic_row(), synthetic_row(hs_code="9999")], "SYNTHETIC.raw")
        assert session.scalar(select(func.count()).select_from(TradeObservation)) == 0


def test_api_explorer_and_fail_closed(engine):
    with Session(engine) as session, session.begin():
        ingest(session, [synthetic_row()], "SYNTHETIC.raw")
    client = TestClient(create_app(engine))
    assert client.get("/api/v1/health").json()["models"] == "baselines_available_unvalidated"
    assert len(client.get("/api/v1/products").json()) >= 18
    assert client.get("/api/v1/trade").json() == []
    response = client.get(
        "/api/v1/trade", params={"include_synthetic": True, "product_id": "rice", "partner": "682"}
    )
    assert response.status_code == 200
    assert response.json()[0]["label"].startswith("SYNTHETIC")
    assert client.get("/api/v1/trade?as_of=2025-02-15").status_code == 422
    assert client.get("/api/v1/trade?limit=1001").status_code == 422
    status = client.get("/api/v1/opportunities").json()
    assert status["status"] == "BLOCKED_OR_UNVERIFIED" and status["score"] is None
    assert status["items"] == []
    assert client.post("/api/v1/feedback", json={}).status_code == 401


def synthetic_comtrade() -> dict:
    """SYNTHETIC response matching the expected documented field names."""
    return {
        "synthetic": True,
        "data": [
            {
                "classificationCode": "H6",
                "refYear": 2025,
                "refMonth": 1,
                "period": "202501",
                "cmdCode": "1006",
                "reporterCode": 356,
                "partnerCode": 682,
                "flowCode": "X",
                "netWgt": 2000,
                "primaryValue": 1000,
            }
        ],
    }


def test_comtrade_transport_cache_and_conservative_availability(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=synthetic_comtrade())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        connector = ComtradeConnector(client, tmp_path, min_interval_seconds=0, synthetic=True)
        body, url, raw, observed = connector.fetch("356", "682", "1006", "202501")
        _, _, cached, timestamp = connector.fetch("356", "682", "1006", "202501")
        assert len(calls) == 1 and raw == cached and observed == timestamp
        rows = normalize(body, "rice", url, raw, observed, synthetic=True)
        assert rows[0].synthetic
        manifest = json.loads((tmp_path / "retrievals.jsonl").read_text().splitlines()[0])
        assert manifest["synthetic"] is True
        assert rows[0].published_at == observed
        assert rows[0].availability_basis == "first_observed"
        assert rows[0].quantity_tonnes == 2
        # Mock data stays inside tests and is never persisted as a real observation.


@pytest.mark.parametrize(
    "response,exception",
    [
        (httpx.Response(200, json={"data": [{}] * 500}), ValueError),
        (httpx.Response(200, json={"wrong": []}), TypeError),
        (httpx.Response(429, headers={"Retry-After": "600"}), RuntimeError),
        (httpx.Response(403), httpx.HTTPStatusError),
    ],
)
def test_comtrade_fails_on_unverified_response(tmp_path, response, exception):
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client,
        pytest.raises(exception),
    ):
        ComtradeConnector(client, tmp_path, min_interval_seconds=0, synthetic=True).fetch(
            "356", "682", "1006", "202501"
        )
    assert list(tmp_path.glob("*.raw"))  # Failed responses retained for audit.


def test_comtrade_retries_server_errors(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(503)
            if len(calls) == 1
            else httpx.Response(200, json=synthetic_comtrade())
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ComtradeConnector(client, tmp_path, min_interval_seconds=0, synthetic=True).fetch(
            "356", "682", "1006", "202501"
        )
    assert len(calls) == 2


def test_comtrade_unknown_revision_and_missing_mass(tmp_path):
    body = synthetic_comtrade()
    raw = tmp_path / ("a" * 64 + ".raw")
    for key, value in [("classificationCode", "H5"), ("netWgt", None)]:
        data = json.loads(json.dumps(body))
        data["data"][0][key] = value
        with pytest.raises(ValueError):
            normalize(data, "rice", "https://example.org/SYNTHETIC", raw, NOW, synthetic=True)


def test_indian_csv_preserves_raw_and_requires_units(tmp_path):
    import csv

    data = synthetic_row().model_dump(
        mode="json", exclude={"source_url", "raw_sha256", "retrieved_at"}
    )
    file = tmp_path / "SYNTHETIC.csv"
    with file.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(data))
        writer.writeheader()
        writer.writerow(data)
    rows, raw = load_indian_csv(
        file, "https://tradestat.commerce.gov.in/", NOW, tmp_path / "raw", "commerce"
    )
    assert rows[0].synthetic and raw.read_bytes() == file.read_bytes()
    file.write_text(file.read_text().replace(",kg,", ",unknown,"))
    with pytest.raises(ValueError, match="CSV row"):
        load_indian_csv(
            file, "https://tradestat.commerce.gov.in/", NOW, tmp_path / "raw", "commerce"
        )


def test_migrations_roundtrip(tmp_path, monkeypatch):
    """Exercise frozen Alembic migration, not only ORM create_all."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    db = make_engine(url)
    assert "trade_observations" in inspect(db).get_table_names()
    init_local(db)
    with Session(db) as session, session.begin():
        ingest(session, [synthetic_row()], "SYNTHETIC.raw")
        assert len(snapshot(session, NOW, include_synthetic=True)) == 1
    db.dispose()
    command.downgrade(config, "base")
    assert "trade_observations" not in inspect(make_engine(url)).get_table_names()
