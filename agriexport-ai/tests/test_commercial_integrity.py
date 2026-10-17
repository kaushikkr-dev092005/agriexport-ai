"""SYNTHETIC accounting and explicit disposable PostgreSQL tenant-integrity checks."""

import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from apps.api.auth import Credential, Principal
from apps.api.main import create_app
from src.database.commercial_models import EvidenceDocument, ExportCostQuote, PolicyRule
from src.database.private_repository import append_record, tenant_session
from src.database.repository import make_engine, seed
from src.ranking.profitability import CORE_COSTS, CostCategory, ShipmentQuote, calculate_margin
from tests.test_commercial import synthetic_quote


@pytest.mark.parametrize("term", ["FOB", "CFR", "CIF", "DAP", "DDP"])
def test_supported_incoterm_cost_allocation(term):
    """Explicit hypothetical payer allocations keep buyer charges out of seller margin."""
    origin = datetime(2025, 3, 1, tzinfo=UTC)
    data = synthetic_quote(origin)
    data["incoterm"] = term
    seller = set(CORE_COSTS)
    if term != "FOB":
        seller.add(CostCategory.FREIGHT)
    if term == "CIF":
        seller.add(CostCategory.INSURANCE)
    if term in {"DAP", "DDP"}:
        seller.add(CostCategory.DESTINATION_TRANSPORT)
    if term == "DDP":
        seller.update({CostCategory.IMPORT_CLEARANCE, CostCategory.DUTIES, CostCategory.TAXES})
    for line in data["costs"]:
        if line["category"] in seller:
            line["payer"] = "seller"
            line["money"] = dict(data["net_selling_price"], amount="10")
        else:
            line["payer"] = "buyer"
            line["money"] = None
    result = calculate_margin(ShipmentQuote.model_validate(data), origin)
    assert result["expected_margin_per_tonne"] == str(1000 - len(seller) * 10)


@pytest.mark.parametrize("timing", ["future", "expired"])
def test_individual_price_vintage_overrides_bundle(timing):
    """A current bundle cannot hide an unavailable or expired individual quotation."""
    origin = datetime(2025, 3, 1, tzinfo=UTC)
    data = synthetic_quote(origin)
    money = data["costs"][0]["money"]
    if timing == "future":
        money["published_at"] = (origin + timedelta(days=1)).isoformat()
    else:
        money["expires_at"] = (origin - timedelta(seconds=1)).isoformat()
    result = calculate_margin(ShipmentQuote.model_validate(data), origin)
    assert result["expected_margin_per_tonne"] is None
    assert result["status"] == "NOT_CALCULATED"


@pytest.mark.skipif(
    not os.getenv("POSTGRES_TEST_URL") or os.getenv("AGRI_ALLOW_TEST_ROLE_CREATION") != "1",
    reason="Explicit disposable PostgreSQL and test-role creation opt-in required",
)
def test_postgres_rls_and_cross_tenant_foreign_keys(monkeypatch):
    """Exercise FORCE RLS as a real nonsuperuser without relying on application filters."""
    url = os.environ["POSTGRES_TEST_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    engine = make_engine(url)
    tenant_a = Principal("SYNTHETIC-RLS-A", "SYNTHETIC-actor", frozenset({"admin"}))
    tenant_b = Principal("SYNTHETIC-RLS-B", "SYNTHETIC-actor", frozenset({"admin"}))
    role = "agri_test_" + uuid.uuid4().hex[:12]
    try:
        with tenant_session(engine, tenant_a) as session:
            seed(session)
            append_record(
                session,
                ExportCostQuote,
                tenant_a,
                {},
                "SYNTHETIC.test",
                True,
                product_id="basmati_rice",
                destination="682",
            )
        with tenant_session(engine, tenant_b) as session:
            append_record(
                session,
                ExportCostQuote,
                tenant_b,
                {},
                "SYNTHETIC.test",
                True,
                product_id="basmati_rice",
                destination="682",
            )
            document = append_record(
                session,
                EvidenceDocument,
                tenant_b,
                {},
                "SYNTHETIC.test",
                True,
                source_url="https://example.org/SYNTHETIC",
                content_sha256="0" * 64,
                text_content="SYNTHETIC",
            )
            document_id = document.record_id
        with pytest.raises(IntegrityError), tenant_session(engine, tenant_a) as session:
            append_record(
                session,
                PolicyRule,
                tenant_a,
                {},
                "SYNTHETIC.test",
                True,
                product_id="basmati_rice",
                country_code="682",
                document_id=document_id,
                rule_key="SYNTHETIC-cross-tenant",
            )
        with engine.begin() as connection:
            connection.execute(text(f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOBYPASSRLS'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            connection.execute(
                text(f'GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO "{role}"')
            )
        try:
            restricted_engine = make_engine(
                engine.url.set(username=role).render_as_string(hide_password=False)
            )
            try:
                credentials = {
                    hashlib.sha256(token.encode()).hexdigest(): Credential(
                        tenant_id=principal.tenant_id, actor_id=principal.actor_id, roles={"admin"}
                    )
                    for token, principal in (
                        ("SYNTHETIC-RLS-A", tenant_a),
                        ("SYNTHETIC-RLS-B", tenant_b),
                    )
                }
                client = TestClient(create_app(restricted_engine, credentials))
                headers = {"Authorization": "Bearer SYNTHETIC-RLS-A"}
                quote = client.post(
                    "/api/v1/commercial/quotes", json=synthetic_quote(), headers=headers
                )
                assert quote.status_code == 201, quote.text
                quote_id = quote.json()["record_id"]
                result = client.post(
                    "/api/v1/commercial/evaluate",
                    headers=headers,
                    json={"quote_id": quote_id, "horizon_days": 7},
                )
                assert result.status_code == 201, result.text
                assert result.json()["opportunity_score"] is None
                assert result.json()["expected_margin_per_tonne"] == "450"
                feedback_body = {
                    "decision_id": result.json()["record_id"],
                    "idempotency_key": "SYNTHETIC-postgres-outcome",
                    "stage": "inquiry",
                    "event_date": datetime.now(UTC).isoformat(),
                    "notes": "SYNTHETIC PostgreSQL pilot outcome",
                    "evidence_reference": "SYNTHETIC inquiry",
                }
                response = client.post("/api/v1/feedback", headers=headers, json=feedback_body)
                assert response.status_code == 201, response.text
                assert response.json()["synthetic"]
                assert (
                    client.get(
                        "/api/v1/feedback", headers={"Authorization": "Bearer SYNTHETIC-RLS-B"}
                    ).json()
                    == []
                )
                assert (
                    client.post(
                        "/api/v1/feedback",
                        headers={"Authorization": "Bearer SYNTHETIC-RLS-B"},
                        json=feedback_body,
                    ).status_code
                    == 404
                )
                assert (
                    client.get(
                        f"/api/v1/commercial/quotes/{quote_id}",
                        headers={"Authorization": "Bearer SYNTHETIC-RLS-B"},
                    ).status_code
                    == 404
                )
                assert len(client.get("/api/v1/commercial/audits", headers=headers).json()) >= 2
            finally:
                restricted_engine.dispose()
            with engine.connect() as connection:
                connection.execute(text(f'SET ROLE "{role}"'))
                connection.commit()
                assert (
                    connection.execute(text("SELECT tenant_id FROM export_cost_quotes")).all() == []
                )
                connection.rollback()
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant, true)"),
                    {"tenant": tenant_a.tenant_id},
                )
                assert {
                    r[0]
                    for r in connection.execute(text("SELECT tenant_id FROM export_cost_quotes"))
                } == {tenant_a.tenant_id}
                connection.rollback()
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant, true)"),
                    {"tenant": tenant_a.tenant_id},
                )
                with pytest.raises(DBAPIError):
                    connection.execute(
                        text(
                            "INSERT INTO export_cost_quotes "
                            "(record_id,tenant_id,created_at,payload,synthetic,product_id,destination) "
                            "VALUES (:id,:tenant,now(),'{}',true,'basmati_rice','682')"
                        ),
                        {"id": uuid.uuid4().hex, "tenant": tenant_b.tenant_id},
                    )
                connection.rollback()
                connection.execute(text("RESET ROLE"))
                connection.commit()
                for name in ("exporter_feedback", "alert_subscriptions", "alerts", "pipeline_runs"):
                    assert connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname=:name"
                        ),
                        {"name": name},
                    ).one() == (True, True)
        finally:
            with engine.begin() as connection:
                connection.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"'))
                connection.execute(text(f'REVOKE ALL ON SCHEMA public FROM "{role}"'))
                connection.execute(text(f'DROP ROLE "{role}"'))
    finally:
        engine.dispose()
