"""Persist honest 7/14/28-day context until high-frequency targets and inputs exist."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.database.models import Prediction, TradeObservation
from src.database.repository import snapshot as trade_snapshot
from src.forecasting.baselines import InsufficientHistory, Observation, forecast_one
from src.forecasting.config import BaselineSettings, load_settings
from src.intelligence.policy_checks import check_eligibility
from src.ranking.opportunity_score import score_opportunity

MODEL_VERSION = "baseline-context-v2"


def next_month(day: date) -> date:
    """Move to next calendar month, without approximate 30-day arithmetic."""
    return date(day.year + (day.month == 12), 1 if day.month == 12 else day.month + 1, 1)


def evidence(row: TradeObservation) -> dict:
    """Expose original dimensions, vintage and source precision with a historical observation."""
    return {
        "observation_id": row.observation_id,
        "period": row.period.isoformat(),
        "quantity_tonnes": str(row.quantity),
        "trade_value": str(row.value),
        "currency": row.currency,
        "reporter": row.reporter,
        "partner": row.partner,
        "flow": row.flow,
        "source_url": row.source_url,
        "raw_sha256": row.raw_sha256,
        "published_at": aware(row.published_at).isoformat(),
        "retrieved_at": aware(row.retrieved_at).isoformat(),
        "revision": row.revision,
        "availability_basis": row.availability_basis,
        "note": "Trade value is customs history, not a current selling quote",
    }


def aware(value: datetime) -> datetime:
    """SQLite local tests strip offsets; all stored timestamps are normalized UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def candidate_series(rows: list[TradeObservation]) -> dict[tuple[str, str], list[TradeObservation]]:
    """Demand belongs to import reporter; Indian export destination belongs to partner."""
    groups = {}
    for row in rows:
        destination = (
            row.reporter
            if row.flow == "M" and row.partner == "000"
            else row.partner
            if row.flow == "X" and row.reporter == "356"
            else None
        )
        if destination and destination not in {"000", "356"}:
            groups.setdefault((row.product_id, destination), []).append(row)
    return groups


def monthly_context(
    rows: list[TradeObservation],
    destination: str,
    origin: datetime,
    settings: BaselineSettings | None = None,
) -> list[dict]:
    """Compute monthly baselines by source only, never weekly disaggregation or cross-source sums."""
    settings = settings or load_settings()
    imports = [
        r for r in rows if r.flow == "M" and r.reporter == destination and r.partner == "000"
    ]
    context = []

    def provider(url: str) -> str:
        """Period-specific query strings identify evidence, not different source providers."""
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    for source in sorted({provider(r.source_url) for r in imports}):
        series = [r for r in imports if provider(r.source_url) == source]
        points = [
            Observation(
                f"{r.product_id}:{destination}:{source}",
                r.period,
                aware(r.published_at),
                float(r.quantity),
                "tonne",
                None,
                r.revision,
                source,
                "monthly",
                r.synthetic,
            )
            for r in series
        ]
        age = (origin.date() - max(r.event_date for r in series)).days
        target_month = max(origin.date().replace(day=1), next_month(max(r.period for r in series)))
        for method in settings.methods:
            value, reason = None, None
            try:
                if age > settings.max_monthly_context_age_days:
                    raise InsufficientHistory(
                        "Latest measured month exceeds configured freshness limit"
                    )
                value = forecast_one(points, target_month, method, "monthly")
            except InsufficientHistory as error:
                reason = str(error)
            context.append(
                {
                    "method": method,
                    "source_url": source,
                    "target_month": target_month.isoformat(),
                    "monthly_quantity_tonnes": value,
                    "status": "UNVALIDATED_BASELINE" if value is not None else "NOT_CALCULATED",
                    "reason": reason,
                    "measured_data_age_days": age,
                }
            )
    return context


def run_forecasts(
    session: Session,
    origin: datetime,
    include_synthetic: bool = False,
    settings: BaselineSettings | None = None,
) -> list[Prediction]:
    """Freeze an origin snapshot and persist per-horizon explanations; caller owns transaction."""
    now = datetime.now(UTC)
    settings = settings or load_settings()
    configuration_hash = hashlib.sha256(settings.model_dump_json().encode()).hexdigest()
    if origin.tzinfo is None or origin > now:
        raise ValueError("Forecast origin must be timezone-aware and not in the future")
    origin = origin.astimezone(UTC)
    rows = trade_snapshot(session, origin, include_synthetic=include_synthetic, limit=1_000_000)
    output = []
    for (product, destination), observations in sorted(candidate_series(rows).items()):
        if len({r.synthetic for r in observations}) > 1:
            raise ValueError("Real and synthetic series must be evaluated separately")
        snapshot_hash = hashlib.sha256(
            json.dumps(sorted(r.observation_id for r in observations)).encode()
        ).hexdigest()
        for horizon in settings.horizons_days:
            identity = json.dumps(
                [
                    product,
                    destination,
                    horizon,
                    origin.isoformat(),
                    MODEL_VERSION,
                    snapshot_hash,
                    configuration_hash,
                ]
            )
            pid = hashlib.sha256(identity.encode()).hexdigest()
            existing = session.get(Prediction, pid)
            if existing:
                output.append(existing)
                continue
            gate = check_eligibility([], product, destination, origin, horizon)
            score = score_opportunity(gate, None)
            payload = {
                "mode": "SEASONAL_OUTLOOK",
                "status": "INSUFFICIENT_HIGH_FREQUENCY_DATA",
                "label": "SYNTHETIC — ILLUSTRATIVE, NOT A LIVE SIGNAL"
                if observations[0].synthetic
                else "UNVERIFIED — NOT A LIVE EXPORT SIGNAL",
                "quantity_tonnes": None,
                "price_forecast": None,
                "opportunity_score": score["score"],
                "expected_margin_per_tonne": None,
                "expected_margin_per_shipment": None,
                "margin_currency": None,
                "forecast_confidence": None,
                "confidence_label": "LOW",
                "prediction_interval": None,
                "ranking_status": score["status"],
                "eligibility_reasons": score["reasons"],
                "reasons": [
                    "Only delayed monthly trade history is available",
                    "Weekly demand and destination price targets are unavailable",
                    "No calibrated probabilities or prediction intervals",
                    "No current exporter stock, selling or delivered-cost quotations",
                ],
                "monthly_baselines": monthly_context(observations, destination, origin, settings),
                "configuration_hash": configuration_hash,
                "configuration": settings.model_dump(mode="json"),
                "evidence": [evidence(r) for r in observations],
                "evaluation": {
                    "status": "NOT_CALCULATED",
                    "reason": "Daily outcomes and historic publication vintages required for weekly backtesting",
                },
                "assumptions": [
                    "No monthly-to-weekly volume allocation",
                    "Historical Indian exports are not destination import demand",
                    "Customs values are not destination wholesale prices",
                ],
                "verify_before_quoting": [
                    "DGFT policy",
                    "Destination import/SPS rules",
                    "Certifications and sanctions",
                    "Stock",
                    "Selling price",
                    "Freight and all delivered costs",
                ],
                "run_type": "CONTEXT_SNAPSHOT"
                if now - origin < timedelta(minutes=5)
                else "HINDCAST_CONTEXT",
            }
            prediction = Prediction(
                prediction_id=pid,
                product_id=product,
                destination=destination,
                horizon_days=horizon,
                forecast_origin=origin,
                created_at=now,
                demand_forecast=None,
                margin_forecast=None,
                confidence=None,
                model_version=MODEL_VERSION,
                input_snapshot_hash=snapshot_hash,
                payload=payload,
                synthetic=observations[0].synthetic,
            )
            session.add(prediction)
            output.append(prediction)
    session.flush()
    return output


def latest_forecasts(
    session: Session,
    as_of: datetime,
    product_id: str | None = None,
    destination: str | None = None,
    horizon_days: int | None = None,
    include_synthetic: bool = False,
) -> list[dict]:
    """Read latest created-and-available version; retain all older immutable runs in storage."""
    if as_of.tzinfo is None:
        raise ValueError("as_of requires timezone")
    as_of = as_of.astimezone(UTC)
    query = select(Prediction).where(
        Prediction.created_at <= as_of, Prediction.forecast_origin <= as_of
    )
    if not include_synthetic:
        query = query.where(Prediction.synthetic.is_(False))
    if product_id:
        query = query.where(Prediction.product_id == product_id)
    if destination:
        query = query.where(Prediction.destination == destination)
    if horizon_days:
        query = query.where(Prediction.horizon_days == horizon_days)
    filtered = query.subquery()
    ranked = select(
        filtered.c.prediction_id,
        func.row_number()
        .over(
            partition_by=[filtered.c.product_id, filtered.c.destination, filtered.c.horizon_days],
            order_by=[filtered.c.forecast_origin.desc(), filtered.c.created_at.desc()],
        )
        .label("rank"),
    ).subquery()
    values = session.scalars(
        select(Prediction)
        .join(ranked, Prediction.prediction_id == ranked.c.prediction_id)
        .where(ranked.c.rank == 1)
        .order_by(Prediction.product_id, Prediction.destination, Prediction.horizon_days)
        .limit(1000)
    )
    return [serialize_prediction(p) for p in values]


def serialize_prediction(p: Prediction) -> dict:
    """Return the complete immutable run, allowing old versions to remain reviewable by ID."""
    return {
        "prediction_id": p.prediction_id,
        "product_id": p.product_id,
        "destination": p.destination,
        "horizon_days": p.horizon_days,
        "forecast_origin": aware(p.forecast_origin).isoformat(),
        "created_at": aware(p.created_at).isoformat(),
        "model_version": p.model_version,
        "input_snapshot_hash": p.input_snapshot_hash,
        "synthetic": p.synthetic,
        **p.payload,
    }
