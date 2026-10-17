"""Public trade/forecast explorer and separate authenticated commercial intelligence API."""

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from src.database.models import Product
from src.database.repository import make_engine, snapshot
from src.forecasting.service import aware, latest_forecasts, serialize_prediction


class TradeResult(BaseModel):
    """Source-labelled trade observation, never a forecast."""

    model_config = ConfigDict(from_attributes=True)
    observation_id: str
    product_id: str
    reporter: str
    partner: str
    period: str
    flow: str
    quantity: Decimal
    unit: str
    value: Decimal
    currency: str
    published_at: str
    event_date: str
    retrieved_at: str
    revision: str
    availability_basis: str
    publication_evidence_url: str | None
    raw_sha256: str
    source_url: str
    synthetic: bool
    label: str


class ForecastResult(BaseModel):
    """Typed core outputs; nulls are part of the contract for unsupported horizons."""

    model_config = ConfigDict(extra="allow")
    prediction_id: str
    product_id: str
    destination: str
    horizon_days: Literal[7, 14, 28]
    forecast_origin: datetime
    created_at: datetime
    model_version: str
    mode: str
    status: str
    quantity_tonnes: float | None
    price_forecast: float | None
    opportunity_score: float | None
    expected_margin_per_tonne: float | None
    forecast_confidence: float | None
    evidence: list[dict]
    monthly_baselines: list[dict]
    eligibility_reasons: list[str]


def create_app(
    engine: Engine | None = None, credentials=None, document_fetcher=None, event_provider=None
) -> FastAPI:
    """App factory with an injected database for deterministic tests."""
    db = engine or make_engine(os.getenv("DATABASE_URL", "sqlite:///./data/local.db"))
    app = FastAPI(title="AgriExport AI — Forecasting and commercial intelligence", version="0.4.0")
    from apps.api.commercial import create_commercial_router

    app.include_router(create_commercial_router(db, credentials, document_fetcher, event_provider))
    from apps.api.pilot import create_pilot_router

    app.include_router(create_pilot_router(db, credentials))
    from apps.api.intelligence import create_intelligence_router

    app.include_router(create_intelligence_router(db))

    @app.exception_handler(IntegrityError)
    async def integrity_conflict(request, error):
        """Concurrent duplicate events fail without disclosing database contents."""
        return JSONResponse(
            status_code=409, content={"detail": "Record conflict; retry after reloading"}
        )

    @app.middleware("http")
    async def audit_rejected_writes(request, call_next):
        """Record authenticated rejected writes, without logging tokens or request bodies."""
        response = await call_next(request)
        if (
            request.method == "POST"
            and (
                request.url.path.startswith("/api/v1/commercial/")
                or request.url.path in {"/api/v1/feedback", "/api/v1/alert-subscriptions"}
            )
            and response.status_code >= 400
        ):
            principal = getattr(request.state, "principal", None)
            if principal is not None:
                import uuid

                from src.database.commercial_models import AuditLog
                from src.database.private_repository import tenant_session

                with tenant_session(db, principal) as session:
                    session.add(
                        AuditLog(
                            record_id=uuid.uuid4().hex,
                            tenant_id=principal.tenant_id,
                            created_at=datetime.now(UTC),
                            actor_id=principal.actor_id,
                            action="write.rejected",
                            entity_id="request",
                            payload={"path": request.url.path, "status_code": response.status_code},
                            synthetic=False,
                        )
                    )
        return response

    @app.get("/api/v1/health")
    def health() -> dict:
        """Surface unavailable DB and absent forecasting separately."""
        try:
            with db.connect() as connection:
                connection.execute(text("SELECT 1 FROM products LIMIT 1"))
                connection.execute(text("SELECT 1 FROM predictions LIMIT 1"))
                connection.execute(text("SELECT 1 FROM export_cost_quotes LIMIT 1"))
        except Exception as error:
            raise HTTPException(503, "Database/schema unavailable; run migrations") from error
        return {
            "status": "ok",
            "phase": 4,
            "commercial_engine": "quotation_accounting_and_reviewed_evidence",
            "policy_feeds": "not_configured_manual_review_required",
            "private_auth": "configured"
            if credentials or os.getenv("AGRI_AUTH_CREDENTIALS")
            else "not_configured_fail_closed",
            "database": "reachable",
            "pipeline": "configured_workflows_require_running_scheduler",
            "models": "baselines_available_unvalidated",
            "baselines": ["last_value", "seasonal_naive", "seasonal_mean"],
            "measured_ml_value": "not_established",
            "source_freshness": "unverified",
            "live_opportunities": False,
        }

    @app.get("/api/v1/products")
    def products() -> list[dict]:
        """Expose broad catalogue with unresolved legal mappings."""
        from sqlalchemy import select

        with Session(db) as session:
            return [
                p.metadata_json
                for p in session.scalars(select(Product).order_by(Product.product_id))
            ]

    @app.get("/api/v1/trade", response_model=list[TradeResult])
    def trade(
        as_of: datetime | None = None,
        product_id: str | None = None,
        partner: str | None = Query(None, pattern=r"^\d{3}$"),
        include_synthetic: bool = False,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> list[dict]:
        """Explore product/country snapshots; preserve source and currency separation."""
        at = as_of or datetime.now(UTC)
        if at.tzinfo is None:
            raise HTTPException(422, "as_of requires timezone")
        with Session(db) as session:
            rows = snapshot(session, at, product_id, partner, include_synthetic, limit, offset)
            return [
                {
                    "observation_id": r.observation_id,
                    "product_id": r.product_id,
                    "reporter": r.reporter,
                    "partner": r.partner,
                    "period": r.period.isoformat(),
                    "flow": r.flow,
                    "quantity": r.quantity,
                    "unit": r.unit,
                    "value": r.value,
                    "currency": r.currency,
                    "published_at": r.published_at.replace(tzinfo=UTC).isoformat()
                    if r.published_at.tzinfo is None
                    else r.published_at.isoformat(),
                    "source_url": r.source_url,
                    "event_date": r.event_date.isoformat(),
                    "retrieved_at": r.retrieved_at.replace(tzinfo=UTC).isoformat()
                    if r.retrieved_at.tzinfo is None
                    else r.retrieved_at.isoformat(),
                    "revision": r.revision,
                    "availability_basis": r.availability_basis,
                    "publication_evidence_url": r.publication_evidence_url,
                    "raw_sha256": r.raw_sha256,
                    "synthetic": r.synthetic,
                    "label": "SYNTHETIC — ILLUSTRATIVE, NOT A LIVE SIGNAL"
                    if r.synthetic
                    else "Historical observation; not an export recommendation",
                }
                for r in rows
            ]

    @app.get("/api/v1/forecasts", response_model=list[ForecastResult])
    def forecasts(
        as_of: datetime | None = None,
        product_id: str | None = None,
        destination: str | None = Query(None, pattern=r"^\d{3}$"),
        horizon_days: Literal[7, 14, 28] | None = None,
        include_synthetic: bool = False,
    ) -> list[dict]:
        """Read stored versioned forecasts/context; never fabricate results on API access."""
        at = as_of or datetime.now(UTC)
        if at.tzinfo is None:
            raise HTTPException(422, "as_of requires timezone")
        with Session(db) as session:
            return latest_forecasts(
                session, at, product_id, destination, horizon_days, include_synthetic
            )

    @app.get("/api/v1/opportunities")
    def opportunities() -> dict:
        """Expose blocked candidates while eligible ranking awaits all verified components."""
        with Session(db) as session:
            blocked = [
                {
                    "prediction_id": p["prediction_id"],
                    "product_id": p["product_id"],
                    "destination": p["destination"],
                    "horizon_days": p["horizon_days"],
                    "score": None,
                    "expected_margin": None,
                    "forecast_confidence": None,
                    "status": p["ranking_status"],
                    "reasons": p["eligibility_reasons"],
                    "label": p["label"],
                }
                for p in latest_forecasts(session, datetime.now(UTC))
            ]
        return {
            "items": [],
            "blocked_items": blocked,
            "status": "BLOCKED_OR_UNVERIFIED",
            "score": None,
            "expected_margin": None,
            "forecast_confidence": None,
            "reasons": [
                "Baselines are unvalidated; high-frequency inputs unavailable",
                "Commercial quotations unavailable",
                "DGFT, destination import, SPS/certification and sanctions unverified",
            ],
        }

    @app.get("/api/v1/opportunities/{prediction_id}", response_model=ForecastResult)
    @app.get("/api/v1/forecasts/{prediction_id}", response_model=ForecastResult)
    def opportunity_detail(prediction_id: str) -> dict:
        """Full evidence and unresolved checks, including blocked candidates."""
        from src.database.models import Prediction

        with Session(db) as session:
            prediction = session.get(Prediction, prediction_id)
            if (
                prediction is None
                or prediction.synthetic
                or aware(prediction.created_at) > datetime.now(UTC)
                or aware(prediction.forecast_origin) > datetime.now(UTC)
            ):
                raise HTTPException(404, "Opportunity/context not found")
            return serialize_prediction(prediction)

    return app
