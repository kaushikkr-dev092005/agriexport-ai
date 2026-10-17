"""All quotes, FX, policies, risks, credentials and event text here are SYNTHETIC fixtures."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from apps.api.auth import Credential, Principal
from apps.api.main import create_app
from src.database.commercial_models import ExportCostQuote
from src.database.models import Prediction
from src.database.repository import init_local, make_engine
from src.intelligence.evidence import DocumentFetcher
from src.ranking.commercial import decide
from src.ranking.profitability import CORE_COSTS, CostCategory, ShipmentQuote, calculate_margin


def synthetic_quote(origin: datetime | None = None) -> dict:
    """A hypothetical fixed 20-tonne CIF quote; every seller zero is explicitly documented."""
    origin = origin or datetime.now(UTC)
    stamp = {
        "quoted_at": (origin - timedelta(minutes=2)).isoformat(),
        "published_at": (origin - timedelta(minutes=1)).isoformat(),
        "expires_at": (origin + timedelta(days=60)).isoformat(),
    }
    costs = []
    for category in CostCategory:
        seller = category in CORE_COSTS or category in {
            CostCategory.FREIGHT,
            CostCategory.INSURANCE,
        }
        amount, basis = (
            ("500", "per_tonne")
            if category == CostCategory.PROCUREMENT
            else (
                ("1000", "per_shipment") if category == CostCategory.FREIGHT else ("0", "per_tonne")
            )
        )
        costs.append(
            {
                "category": category.value,
                "payer": "seller" if seller else "buyer",
                "money": {
                    "amount": amount,
                    "currency": "USD",
                    "basis": basis,
                    "evidence_reference": "SYNTHETIC explicit quotation, including any zero cost",
                    **stamp,
                }
                if seller
                else None,
                "note": "SYNTHETIC explicit cost allocation",
            }
        )
    return {
        "product_id": "basmati_rice",
        "destination": "682",
        "incoterm": "CIF",
        "transport_mode": "sea",
        "named_place": "SYNTHETIC destination port",
        "shipment_tonnes": "20",
        "buyer_quantity_tonnes": "25",
        "verified_stock_tonnes": "30",
        "logistics_capacity_tonnes": "20",
        "capacity_evidence_reference": "SYNTHETIC stock and capacity quote",
        "buyer_reference": "SYNTHETIC-BUYER",
        "logistics_reference": "SYNTHETIC-CARRIER",
        "reporting_currency": "USD",
        "net_selling_price": {
            "amount": "1000",
            "currency": "USD",
            "basis": "per_tonne",
            "evidence_reference": "SYNTHETIC buyer quote",
            **stamp,
        },
        "costs": costs,
        "fx_rates": [],
        "quoted_at": (origin - timedelta(minutes=2)).isoformat(),
        "published_at": (origin - timedelta(minutes=1)).isoformat(),
        "expires_at": (origin + timedelta(days=60)).isoformat(),
        "contract_review_reference": "SYNTHETIC Incoterm contract review",
        "synthetic": True,
    }


def test_decimal_margin_fixed_shipment_and_missing_inputs():
    origin = datetime(2025, 3, 1, tzinfo=UTC)
    data = synthetic_quote(origin)
    result = calculate_margin(ShipmentQuote.model_validate(data), origin)
    assert result["synthetic"] and result["label"].startswith("SYNTHETIC")
    assert Decimal(result["total_seller_cost_per_tonne"]) == 550
    assert Decimal(result["expected_margin_per_tonne"]) == 450
    assert Decimal(result["expected_profit_per_shipment"]) == 9000
    data["verified_stock_tonnes"] = "10"
    limited = calculate_margin(ShipmentQuote.model_validate(data), origin)
    assert (
        limited["feasible_quantity_tonnes"] == "10" and limited["expected_margin_per_tonne"] is None
    )


def test_fx_direction_kg_normalization_and_future_availability():
    origin = datetime(2025, 3, 1, tzinfo=UTC)
    data = synthetic_quote(origin)
    data["costs"][0]["money"].update(amount="50", currency="INR", basis="per_kg")
    data["fx_rates"] = [
        {
            "base_currency": "INR",
            "quote_currency": "USD",
            "rate": "0.012",
            "rate_date": "2025-03-01",
            "published_at": origin.isoformat(),
            "valid_until": (origin + timedelta(days=30)).isoformat(),
            "source_url": "https://example.org/SYNTHETIC/fx",
            "verified": True,
        }
    ]
    result = calculate_margin(ShipmentQuote.model_validate(data), origin)
    assert Decimal(result["total_seller_cost_per_tonne"]) == 650
    assert Decimal(result["expected_margin_per_tonne"]) == 350
    data["fx_rates"][0]["published_at"] = (origin + timedelta(days=1)).isoformat()
    assert (
        calculate_margin(ShipmentQuote.model_validate(data), origin)["expected_margin_per_tonne"]
        is None
    )
    data["fx_rates"] = []
    assert (
        calculate_margin(ShipmentQuote.model_validate(data), origin)["status"] == "NOT_CALCULATED"
    )


@pytest.mark.parametrize("change", ["missing", "duplicate", "ambiguous", "payer", "mode", "naive"])
def test_ambiguous_costs_and_incoterm_mismatch_rejected(change):
    data = synthetic_quote()
    if change == "missing":
        data["costs"].pop()
    elif change == "duplicate":
        data["costs"].append(data["costs"][0])
    elif change == "ambiguous":
        data["costs"][0]["money"]["basis"] = "per_container"
    elif change == "payer":
        data["costs"][0]["payer"] = "buyer"
    elif change == "mode":
        data["transport_mode"] = "air"
    else:
        data["published_at"] = "2025-03-01T00:00:00"
    with pytest.raises(ValidationError):
        ShipmentQuote.model_validate(data)


TOKENS = {
    "SYNTHETIC-A-admin": ("SYNTHETIC-A", {"admin"}),
    "SYNTHETIC-A-exporter": ("SYNTHETIC-A", {"exporter"}),
    "SYNTHETIC-A-analyst": ("SYNTHETIC-A", {"analyst"}),
    "SYNTHETIC-B-admin": ("SYNTHETIC-B", {"admin"}),
}
TEXT = (
    "SYNTHETIC fixture only. Rule 10063020 covers basmati rice in this hypothetical example. "
    "SYNTHETIC payment and logistics evidence reviewed for testing only. "
    "SYNTHETIC shipping disruption affects rice deliveries; inspect supporting source text."
)


class SyntheticProvider:
    """No network or real LLM; structured test output is explicitly synthetic."""

    def __init__(self):
        self.origin = datetime.now(UTC)
        self.last_request = None
        self.add_quantities = False

    def extract(self, request: dict) -> dict:
        self.last_request = request
        event = {
            "product_id": "basmati_rice",
            "country_code": "682",
            "event_type": "shipping",
            "event_date": self.origin.isoformat(),
            "impact_direction": "increase",
            "confidence": 0.8,
            "expiry_date": (self.origin + timedelta(days=10)).isoformat(),
            "source_url": request["source_url"],
            "evidence_quote": "SYNTHETIC shipping disruption affects rice deliveries",
        }
        if self.add_quantities:
            event["quantity_tonnes"] = 999
        return {"events": [event, dict(event)]}


@pytest.fixture
def commercial_app(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'commercial.db'}")
    init_local(engine)
    credentials = {
        hashlib.sha256(token.encode()).hexdigest(): Credential(
            tenant_id=tenant, actor_id=token, roles=roles
        )
        for token, (tenant, roles) in TOKENS.items()
    }
    provider = SyntheticProvider()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, text=f"<html><body>{TEXT}</body></html>", headers={"content-type": "text/html"}
            )
        )
    ) as transport:
        fetcher = DocumentFetcher(transport, tmp_path / "raw", synthetic=True)
        app = create_app(engine, credentials, fetcher, provider)
        yield TestClient(app), engine, provider
    engine.dispose()


def auth(token: str = "SYNTHETIC-A-admin") -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_private_auth_rbac_tenant_isolation_and_audit(commercial_app):
    client, _, _ = commercial_app
    assert client.post("/api/v1/commercial/quotes", json=synthetic_quote()).status_code == 401
    quote = client.post("/api/v1/commercial/quotes", json=synthetic_quote(), headers=auth()).json()
    quote_id = quote["record_id"]
    assert client.get("/api/v1/commercial/quotes", headers=auth("SYNTHETIC-B-admin")).json() == []
    assert (
        client.get(
            f"/api/v1/commercial/quotes/{quote_id}", headers=auth("SYNTHETIC-B-admin")
        ).status_code
        == 404
    )
    rejected = client.post(
        "/api/v1/commercial/policies/review", json={}, headers=auth("SYNTHETIC-A-exporter")
    )
    assert rejected.status_code == 403
    evaluation = client.post(
        "/api/v1/commercial/evaluate",
        json={"quote_id": quote_id, "horizon_days": 7},
        headers=auth(),
    ).json()
    assert evaluation["status"] == "BLOCKED_OR_UNVERIFIED"
    assert evaluation["opportunity_score"] is None
    assert Decimal(evaluation["expected_margin_per_tonne"]) == 450
    assert evaluation["forecast_confidence"] is None
    assert (
        client.get(
            "/api/v1/commercial/decisions/" + evaluation["record_id"],
            headers=auth("SYNTHETIC-B-admin"),
        ).status_code
        == 404
    )
    audits = client.get("/api/v1/commercial/audits", headers=auth()).json()
    assert {a["action"] for a in audits} >= {"quote.create", "decision.evaluate", "write.rejected"}
    assert (
        client.get("/api/v1/commercial/audits", headers=auth("SYNTHETIC-A-exporter")).status_code
        == 403
    )
    assert client.get("/api/v1/forecasts").json() == []


def test_text_extraction_citations_dedup_no_statistics_or_quote_leaks(commercial_app):
    client, _, provider = commercial_app
    client.post("/api/v1/commercial/quotes", json=synthetic_quote(), headers=auth())
    document = client.post(
        "/api/v1/commercial/documents/fetch",
        json={"source_url": "https://www.sfda.gov.sa/SYNTHETIC"},
        headers=auth(),
    ).json()
    request = {"document_id": document["record_id"], "query": "rice shipping"}
    events = client.post("/api/v1/commercial/events/extract", json=request, headers=auth())
    assert events.status_code == 201 and len(events.json()) == 1
    assert events.json()[0]["review_status"] == "UNVERIFIED" and events.json()[0]["synthetic"]
    assert "SYNTHETIC-BUYER" not in str(provider.last_request)
    assert (
        client.post("/api/v1/commercial/events/extract", json=request, headers=auth()).json() == []
    )
    assert client.get("/api/v1/commercial/events", headers=auth("SYNTHETIC-B-admin")).json() == []
    assert (
        client.post(
            "/api/v1/commercial/events/extract", json=request, headers=auth("SYNTHETIC-B-admin")
        ).status_code
        == 404
    )
    provider.add_quantities = True
    assert (
        client.post("/api/v1/commercial/events/extract", json=request, headers=auth()).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/commercial/documents/fetch",
            json={"source_url": "http://127.0.0.1/private"},
            headers=auth(),
        ).status_code
        == 422
    )


def test_reviewed_synthetic_decision_and_policy_ban_override(commercial_app):
    client, engine, _ = commercial_app
    now = datetime.now(UTC)
    quote = client.post(
        "/api/v1/commercial/quotes", json=synthetic_quote(now), headers=auth()
    ).json()
    with Session(engine) as session, session.begin():
        session.add(
            Prediction(
                prediction_id="SYNTHETIC-prediction",
                product_id="basmati_rice",
                destination="682",
                horizon_days=7,
                forecast_origin=now - timedelta(minutes=2),
                created_at=now - timedelta(minutes=1),
                demand_forecast=Decimal(100),
                margin_forecast=None,
                confidence=Decimal("0.8"),
                model_version="SYNTHETIC-VALIDATED-FIXTURE-NOT-REAL-ML",
                input_snapshot_hash="a" * 64,
                payload={
                    "model_validation_status": "VALIDATED_OUT_OF_TIME",
                    "confidence_calibration_status": "CALIBRATED_OUT_OF_TIME",
                },
                synthetic=True,
            )
        )
    reviewed = client.post(
        f"/api/v1/commercial/quotes/{quote['record_id']}/review",
        headers=auth(),
        json={
            "review_reference": "SYNTHETIC reviewed buyer/stock/cost evidence",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "prediction_id": "SYNTHETIC-prediction",
            "normalized_components": {
                "demand": 80,
                "indian_supply": 70,
                "profit": 60,
                "accessibility": 50,
                "confidence": 80,
            },
            "normalization_reference": "SYNTHETIC explicit unvalidated component normalization",
        },
    )
    assert reviewed.status_code == 201
    quote_id = reviewed.json()["record_id"]
    sources = {
        category: client.post(
            "/api/v1/commercial/documents/fetch", headers=auth(), json={"source_url": url}
        ).json()["record_id"]
        for category, url in {
            "DGFT": "https://content.dgft.gov.in/SYNTHETIC",
            "DESTINATION_IMPORT": "https://www.sfda.gov.sa/SYNTHETIC",
            "SANCTIONS": "https://main.un.org/SYNTHETIC",
        }.items()
    }
    for category in ("DGFT", "DESTINATION_IMPORT", "SPS_CERTIFICATION", "SANCTIONS"):
        body = {
            "document_id": sources[
                "DESTINATION_IMPORT" if category == "SPS_CERTIFICATION" else category
            ],
            "rule_key": "SYNTHETIC-" + category,
            "product_id": "basmati_rice",
            "country_code": "682",
            "hs_code": "10063020",
            "category": category,
            "decision": "ALLOW",
            "effective_from": (now - timedelta(days=1)).isoformat(),
            "effective_to": (now + timedelta(days=30)).isoformat(),
            "review_valid_until": (now + timedelta(hours=12)).isoformat(),
            "evidence_excerpt": "Rule 10063020 covers basmati rice in this hypothetical example.",
            "review_notes": "SYNTHETIC-BUYER SYNTHETIC-CARRIER hypothetical screening of all applicable regimes and certificates",
            "quote_id": quote_id,
        }
        response = client.post("/api/v1/commercial/policies/review", json=body, headers=auth())
        assert response.status_code == 201, response.text
    for kind in ("payment", "logistics"):
        response = client.post(
            "/api/v1/commercial/risks/review",
            headers=auth(),
            json={
                "document_id": sources["DESTINATION_IMPORT"],
                "country_code": "682",
                "indicator": kind,
                "level": "LOW",
                "valid_until": (now + timedelta(days=30)).isoformat(),
                "evidence_excerpt": "SYNTHETIC payment and logistics evidence reviewed for testing only.",
                "review_notes": "SYNTHETIC manually reviewed risk example",
            },
        )
        assert response.status_code == 201
    request = {"quote_id": quote_id, "prediction_id": "SYNTHETIC-prediction", "horizon_days": 7}
    response = client.post("/api/v1/commercial/evaluate", headers=auth(), json=request)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["synthetic"] and result["label"].startswith("SYNTHETIC")
    assert result["opportunity_score"] == pytest.approx(67.5), result["reasons"]
    assert (
        result["forecast_confidence"] == 0.8 and Decimal(result["expected_margin_per_tonne"]) == 450
    )
    assert len(result["policy_evidence"]) == 4 and all(
        p["source_url"] for p in result["policy_evidence"]
    )
    with Session(engine) as session:
        historical = decide(
            session,
            Principal("SYNTHETIC-A", "SYNTHETIC-A-admin", frozenset({"admin"})),
            session.get(ExportCostQuote, quote_id),
            session.get(Prediction, "SYNTHETIC-prediction"),
            now,
            7,
        )
        assert historical["opportunity_score"] is None
        assert historical["policy_evidence_ids"] == []
        assert any("not yet available" in reason for reason in historical["reasons"])
    mismatched = client.post(
        "/api/v1/commercial/evaluate", headers=auth(), json={**request, "horizon_days": 14}
    ).json()
    assert mismatched["opportunity_score"] is None and any(
        "Prediction scope" in reason for reason in mismatched["reasons"]
    )
    body.update(
        document_id=sources["DGFT"],
        category="DGFT",
        rule_key="SYNTHETIC-future-ban",
        decision="BLOCK",
        effective_from=(now + timedelta(days=2)).isoformat(),
    )
    assert (
        client.post("/api/v1/commercial/policies/review", json=body, headers=auth()).status_code
        == 201
    )
    blocked = client.post("/api/v1/commercial/evaluate", json=request, headers=auth()).json()
    assert blocked["opportunity_score"] is None and any(
        "restriction" in reason for reason in blocked["reasons"]
    )
