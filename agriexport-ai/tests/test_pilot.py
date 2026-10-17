"""All pilot outcomes and decision transitions in these tests are explicitly SYNTHETIC."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from apps.api.auth import Principal
from pipelines.daily_refresh import RefreshConfig, run_daily
from src.database.commercial_models import CommercialDecision
from src.database.pilot_models import AlertRecord
from src.database.private_repository import append_record, tenant_session
from src.ranking.alerts import emit_alerts, material_changes
from tests.test_commercial import auth, synthetic_quote

PREFERENCE = {
    "currency": "USD",
    "margin_threshold_per_tonne": "500",
    "forecast_shift_fraction": "0.2",
}
ELIGIBLE = {
    "status": "SCORED_WITH_UNVALIDATED_WEIGHTS",
    "currency": "USD",
    "expected_margin_per_tonne": "450",
    "demand_quantity_tonnes": "100",
}


def decision(client):
    """Create an explicitly SYNTHETIC quote with a genuinely blocked calculation."""
    quote = client.post("/api/v1/commercial/quotes", json=synthetic_quote(), headers=auth()).json()
    response = client.post(
        "/api/v1/commercial/evaluate",
        json={"quote_id": quote["record_id"], "horizon_days": 7},
        headers=auth(),
    )
    assert response.status_code == 201
    return response.json()


def test_feedback_idempotency_actual_accounting_rbac_and_tenant(commercial_app):
    client, _, _ = commercial_app
    result = decision(client)
    body = {
        "decision_id": result["record_id"],
        "idempotency_key": "SYNTHETIC-shipment-1",
        "stage": "shipped",
        "event_date": datetime.now(UTC).isoformat(),
        "notes": "SYNTHETIC completed shipment only",
        "quantity_tonnes": "20",
        "currency": "USD",
        "actual_revenue": "20000",
        "actual_total_cost": "12000",
        "shipment_success": True,
        "evidence_reference": "SYNTHETIC invoice fixture",
    }
    assert client.post("/api/v1/feedback", json=body).status_code == 401
    assert (
        client.post("/api/v1/feedback", json=body, headers=auth("SYNTHETIC-A-analyst")).status_code
        == 403
    )
    assert (
        client.post("/api/v1/feedback", json=body, headers=auth("SYNTHETIC-B-admin")).status_code
        == 404
    )
    response = client.post("/api/v1/feedback", json=body, headers=auth())
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["synthetic"] and record["label"].startswith("SYNTHETIC")
    assert record["verification_status"] == "SELF_REPORTED_UNVERIFIED"
    assert (
        record["realised_profit_per_shipment"] == "8000"
        and record["realised_margin_per_tonne"] == "400"
    )
    assert (
        client.post("/api/v1/feedback", json=body, headers=auth()).json()["record_id"]
        == record["record_id"]
    )
    assert (
        client.post(
            "/api/v1/feedback", json={**body, "notes": "SYNTHETIC changed"}, headers=auth()
        ).status_code
        == 409
    )
    assert len(client.get("/api/v1/feedback", headers=auth()).json()) == 1
    assert client.get("/api/v1/feedback", headers=auth("SYNTHETIC-B-admin")).json() == []
    assert (
        client.post(
            "/api/v1/feedback",
            json={
                **body,
                "idempotency_key": "SYNTHETIC-future",
                "event_date": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
            headers=auth(),
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/feedback", json={**body, "stage": "won"}, headers=auth()).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/feedback",
            json={**body, "idempotency_key": "SYNTHETIC-currency", "currency": "INR"},
            headers=auth(),
        ).status_code
        == 422
    )


def test_material_changes_avoid_noise_and_unknown_metrics():
    assert material_changes(None, {"status": "BLOCKED_OR_UNVERIFIED"}, PREFERENCE) == []
    assert material_changes(None, ELIGIBLE, PREFERENCE) == ["NEW_OPPORTUNITY"]
    assert material_changes(ELIGIBLE, dict(ELIGIBLE), PREFERENCE) == []
    assert material_changes(
        ELIGIBLE, {**ELIGIBLE, "expected_margin_per_tonne": "550"}, PREFERENCE
    ) == ["MARGIN_THRESHOLD_CROSSED"]
    assert material_changes(
        ELIGIBLE, {**ELIGIBLE, "demand_quantity_tonnes": "120"}, PREFERENCE
    ) == ["LARGE_FORECAST_SHIFT"]
    assert (
        material_changes(
            ELIGIBLE,
            {**ELIGIBLE, "currency": "INR", "expected_margin_per_tonne": "999"},
            PREFERENCE,
        )
        == []
    )
    assert material_changes(
        ELIGIBLE,
        {"status": "BLOCKED_OR_UNVERIFIED", "reasons": ["DGFT: restriction applies within window"]},
        PREFERENCE,
    ) == ["POLICY_INVALIDATION"]


def test_alert_persistence_dedup_tenant_scoping_and_subscription_disable(commercial_app):
    client, engine, _ = commercial_app
    result = decision(client)
    pref = {
        "product_id": "basmati_rice",
        "destination": "682",
        "horizon_days": 7,
        **PREFERENCE,
        "enabled": True,
        "synthetic": True,
    }
    assert client.post("/api/v1/alert-subscriptions", json=pref, headers=auth()).status_code == 201
    principal = Principal("SYNTHETIC-A", "SYNTHETIC-actor", frozenset({"admin"}))
    with tenant_session(engine, principal) as session:
        record = append_record(
            session,
            CommercialDecision,
            principal,
            {**result, **ELIGIBLE},
            "SYNTHETIC.transition",
            True,
            quote_id=result["quote_id"],
            prediction_id=None,
        )
        assert emit_alerts(session, principal, record) == 1
        assert emit_alerts(session, principal, record) == 0
    alerts = client.get("/api/v1/alerts", headers=auth()).json()
    assert len(alerts) == 1 and alerts[0]["kind"] == "NEW_OPPORTUNITY" and alerts[0]["synthetic"]
    assert alerts[0]["delivery"] == "DASHBOARD_ONLY" and alerts[0]["as_of"]
    assert client.get("/api/v1/alerts", headers=auth("SYNTHETIC-B-admin")).json() == []
    assert (
        client.post(
            "/api/v1/alert-subscriptions", json={**pref, "enabled": False}, headers=auth()
        ).status_code
        == 201
    )
    with tenant_session(engine, principal) as session:
        record = append_record(
            session,
            CommercialDecision,
            principal,
            {**result, **ELIGIBLE, "expected_margin_per_tonne": "550"},
            "SYNTHETIC.transition",
            True,
            quote_id=result["quote_id"],
            prediction_id=None,
        )
        assert emit_alerts(session, principal, record) == 0
        assert len(list(session.scalars(select(AlertRecord)))) == 1


def test_daily_empty_sources_are_degraded_and_exclude_synthetic_quotes(commercial_app):
    client, engine, _ = commercial_app
    decision(client)
    principal = Principal("SYNTHETIC-A", "SYNTHETIC-operator", frozenset({"admin"}))
    result = run_daily(engine, RefreshConfig(), [principal])
    assert result["status"] == "DEGRADED" and result["forecast_contexts"] == 0
    assert result["outbound_messages"] == 0
    runs = client.get("/api/v1/pipeline-runs", headers=auth()).json()
    assert runs[0]["decisions"] == 0 and runs[0]["feed_status"] == "NOT_CONFIGURED"
    assert client.get("/api/v1/pipeline-runs", headers=auth("SYNTHETIC-B-admin")).json() == []


def test_country_and_commodity_endpoints_never_impute_missing_data(commercial_app):
    client, _, _ = commercial_app
    assert len(client.get("/api/v1/countries").json()) >= 10
    country = client.get("/api/v1/markets/682").json()
    assert country["import_dependence"] is None and country["current_suppliers"] is None
    assert country["restrictions"] == "UNVERIFIED"
    assert client.get("/api/v1/markets/999").status_code == 404
    product = client.get("/api/v1/commodities/basmati_rice").json()
    assert product["indian_supply_tonnes"] is None and product["current_price"] is None


def test_quote_cost_revisions_preserve_lineage_and_reset_approval(commercial_app):
    client, _, _ = commercial_app
    original = client.post(
        "/api/v1/commercial/quotes", json=synthetic_quote(), headers=auth()
    ).json()
    changed = synthetic_quote()
    changed["net_selling_price"]["amount"] = "1100"
    path = f"/api/v1/commercial/quotes/{original['record_id']}/revision"
    assert client.post(path, json=changed, headers=auth("SYNTHETIC-B-admin")).status_code == 404
    revised = client.post(path, json=changed, headers=auth()).json()
    assert (
        revised["original_quote_id"] == original["record_id"]
        and revised["review_status"] == "UNVERIFIED"
    )
    assert (
        client.get(f"/api/v1/commercial/quotes/{original['record_id']}", headers=auth()).json()[
            "accounting"
        ]["expected_margin_per_tonne"]
        == "450"
    )
    assert (
        client.get(f"/api/v1/commercial/quotes/{revised['record_id']}", headers=auth()).json()[
            "accounting"
        ]["expected_margin_per_tonne"]
        == "550"
    )


def test_source_outage_persists_degraded_pipeline_status(commercial_app):
    client, engine, _ = commercial_app
    config = RefreshConfig.model_validate(
        {
            "jobs": [
                {
                    "source": "comtrade",
                    "product_id": "rice",
                    "hs_code": "1006",
                    "period": "202401",
                    "partner": "000",
                    "reporter": "156",
                    "flow": "M",
                }
            ]
        }
    )

    def unavailable(job, db):
        raise OSError("SYNTHETIC source outage")

    result = run_daily(
        engine,
        config,
        [Principal("SYNTHETIC-A", "SYNTHETIC-operator", frozenset({"admin"}))],
        ingestor=unavailable,
    )
    assert result["status"] == "DEGRADED"
    assert result["source_results"] == [
        {"source": "comtrade", "status": "UNVERIFIED_SOURCE_FAILED"}
    ]
    assert client.get("/api/v1/pipeline-runs", headers=auth()).json()[0]["status"] == "DEGRADED"
