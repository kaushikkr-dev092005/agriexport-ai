"""Tenant-private pilot feedback and alert inbox; no outbound messaging side effects."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import Engine, select

from apps.api.auth import Principal, load_credentials, require_roles
from apps.api.commercial import view
from src.database.commercial_models import CommercialDecision
from src.database.models import Country, Product
from src.database.pilot_models import AlertRecord, AlertSubscription, ExporterFeedback, PipelineRun
from src.database.private_repository import append_record, owned, records, tenant_session
from src.forecasting.service import aware
from src.ranking.profitability import Currency, StrictModel


class FeedbackInput(StrictModel):
    """Dated, evidence-linked exporter report, separate from verified outcome labels."""

    decision_id: str
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    stage: Literal["inquiry", "quote", "won", "lost", "shipped"]
    event_date: datetime
    notes: str = Field(min_length=1, max_length=2000)
    quantity_tonnes: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    currency: Currency | None = None
    actual_revenue: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    actual_total_cost: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    shipment_success: bool | None = None
    evidence_reference: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def outcomes(self) -> "FeedbackInput":
        amounts = [self.actual_revenue, self.actual_total_cost]
        if any(x is not None for x in amounts) and (
            self.stage != "shipped"
            or any(x is None for x in amounts)
            or self.quantity_tonnes is None
            or self.currency is None
        ):
            raise ValueError(
                "Realised accounting requires a shipment, quantity, currency and both actual amounts"
            )
        if self.shipment_success is not None and self.stage != "shipped":
            raise ValueError("Shipment success is only reported after shipment")
        return self


class SubscriptionInput(StrictModel):
    """Currency-specific material-change preferences for one product/market/window."""

    product_id: str
    destination: str = Field(pattern=r"^\d{3}$")
    horizon_days: Literal[7, 14, 28]
    currency: Currency
    margin_threshold_per_tonne: Decimal = Field(allow_inf_nan=False)
    forecast_shift_fraction: Decimal = Field(
        default=Decimal("0.20"), gt=0, le=1, allow_inf_nan=False
    )
    enabled: bool = True
    synthetic: bool = False


def create_pilot_router(engine: Engine, credentials=None) -> APIRouter:
    """Derive tenant from token metadata; never accept tenant IDs in request bodies."""
    registry = credentials if credentials is not None else load_credentials()
    read = require_roles(registry, {"exporter", "analyst", "admin"})
    write = require_roles(registry, {"exporter", "admin"})
    router = APIRouter(prefix="/api/v1", tags=["Pilot feedback and alerts"])

    @router.post("/feedback", status_code=201)
    def add_feedback(body: FeedbackInput, principal: Annotated[Principal, Depends(write)]) -> dict:
        with tenant_session(engine, principal) as session:
            decision = owned(session, CommercialDecision, body.decision_id, principal)
            if decision is None:
                raise HTTPException(404, "Decision not found")
            if body.event_date > datetime.now(UTC):
                raise HTTPException(422, "Outcome event date is in the future")
            if body.event_date < aware(decision.created_at):
                raise HTTPException(
                    422,
                    "Outcome predates this stored decision; cannot count as prospective evidence",
                )
            existing = session.scalar(
                select(ExporterFeedback).where(
                    ExporterFeedback.tenant_id == principal.tenant_id,
                    ExporterFeedback.idempotency_key == body.idempotency_key,
                )
            )
            payload = body.model_dump(mode="json")
            if existing:
                if any(existing.payload.get(key) != value for key, value in payload.items()):
                    raise HTTPException(409, "Idempotency key already refers to different feedback")
                return view(existing)
            if body.currency and body.currency != decision.payload["currency"]:
                raise HTTPException(
                    422, "Outcome currency differs from the quoted reporting currency"
                )
            profit = (
                body.actual_revenue - body.actual_total_cost
                if body.actual_revenue is not None
                else None
            )
            payload.update(
                published_at=datetime.now(UTC).isoformat(),
                verification_status="SELF_REPORTED_UNVERIFIED",
                realised_profit_per_shipment=str(profit) if profit is not None else None,
                realised_margin_per_tonne=str(profit / body.quantity_tonnes)
                if profit is not None
                else None,
            )
            return view(
                append_record(
                    session,
                    ExporterFeedback,
                    principal,
                    payload,
                    "feedback.capture",
                    decision.synthetic,
                    decision_id=body.decision_id,
                    idempotency_key=body.idempotency_key,
                )
            )

    @router.get("/feedback")
    def feedback(principal: Annotated[Principal, Depends(read)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(r) for r in records(session, ExporterFeedback, principal)]

    @router.post("/alert-subscriptions", status_code=201)
    def subscribe(body: SubscriptionInput, principal: Annotated[Principal, Depends(write)]) -> dict:
        with tenant_session(engine, principal) as session:
            if not session.get(Product, body.product_id) or not session.get(
                Country, body.destination
            ):
                raise HTTPException(422, "Unknown product/country")
            return view(
                append_record(
                    session,
                    AlertSubscription,
                    principal,
                    body.model_dump(mode="json"),
                    "alert.subscribe",
                    body.synthetic,
                    product_id=body.product_id,
                    destination=body.destination,
                )
            )

    @router.get("/alert-subscriptions")
    def subscriptions(principal: Annotated[Principal, Depends(read)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(r) for r in records(session, AlertSubscription, principal)]

    @router.get("/alerts")
    def alerts(principal: Annotated[Principal, Depends(read)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(r) for r in records(session, AlertRecord, principal)]

    @router.get("/pipeline-runs")
    def pipeline_runs(principal: Annotated[Principal, Depends(read)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(r) for r in records(session, PipelineRun, principal)]

    return router
