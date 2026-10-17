"""Commercial decisions combine tenant evidence, not country need alone."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import Principal
from src.database.commercial_models import CountryRisk, PolicyRule
from src.database.models import Prediction, Product
from src.database.private_repository import records
from src.forecasting.service import aware
from src.intelligence.policy_checks import Eligibility, PolicyEvidence, check_eligibility
from src.ranking.opportunity_score import score_opportunity
from src.ranking.profitability import ShipmentQuote, calculate_margin


def policy_snapshot(
    session: Session, principal: Principal, quote_record, origin: datetime
) -> tuple[list, list]:
    """Select the latest known review per rule key, preserving independent conflicting rules."""
    latest = {}
    evidence, evidence_ids = [], []
    for rule in session.scalars(
        select(PolicyRule)
        .where(
            PolicyRule.tenant_id == principal.tenant_id,
            PolicyRule.product_id == quote_record.product_id,
            PolicyRule.country_code == quote_record.destination,
            PolicyRule.created_at <= origin,
        )
        .order_by(PolicyRule.created_at.desc(), PolicyRule.record_id.desc())
    ):
        if (
            rule.product_id != quote_record.product_id
            or rule.country_code != quote_record.destination
            or aware(rule.created_at) > origin
            or rule.synthetic != quote_record.synthetic
        ):
            continue
        scope = rule.payload.get("quote_id")
        if scope and scope not in {
            quote_record.record_id,
            quote_record.payload.get("original_quote_id"),
        }:
            continue
        key = (rule.rule_key, rule.payload["category"])
        if key in latest:
            continue
        latest[key] = rule
        data = rule.payload
        review_valid = datetime.fromisoformat(
            data["review_valid_until"]
        ) >= origin and origin - datetime.fromisoformat(data["document_retrieved_at"]) <= timedelta(
            hours=24
        )
        evidence.append(
            PolicyEvidence(
                category=data["category"],
                product_id=rule.product_id,
                destination=rule.country_code,
                decision=data["decision"] if review_valid else "UNVERIFIED",
                published_at=datetime.fromisoformat(data["published_at"]),
                verified_at=aware(rule.created_at) if review_valid else None,
                effective_from=datetime.fromisoformat(data["effective_from"]),
                effective_to=datetime.fromisoformat(data["effective_to"]),
                source_url=data["source_url"],
            )
        )
        evidence_ids.append(rule.record_id)
    return evidence, evidence_ids


def risk_snapshot(
    session: Session,
    principal: Principal,
    country: str,
    origin: datetime,
    horizon_days: int,
    synthetic: bool = False,
) -> tuple[list[dict], list[str]]:
    """Country payment/logistics indicators are reviewed inputs, not invented risk statistics."""
    selected = {}
    for record in records(session, CountryRisk, principal, limit=10000):
        if (
            record.country_code == country
            and aware(record.created_at) <= origin
            and record.synthetic == synthetic
        ):
            selected.setdefault(record.payload["indicator"], record)
    values, reasons = [], []
    for kind in ("payment", "logistics"):
        record = selected.get(kind)
        if record is None:
            reasons.append(f"{kind}: country risk evidence missing")
            continue
        data = record.payload
        values.append({"record_id": record.record_id, **data})
        if datetime.fromisoformat(data["valid_until"]) < origin + timedelta(days=horizon_days):
            reasons.append(f"{kind}: risk evidence does not cover the shipment window")
        elif data["level"] in {"HIGH", "UNVERIFIED"}:
            reasons.append(f"{kind}: risk is {data['level']}")
    return values, reasons


def decide(
    session: Session,
    principal: Principal,
    quote_record,
    prediction: Prediction | None,
    origin: datetime,
    horizon_days: int,
) -> dict:
    """Legal gates precede score computation; accounting may still explain a blocked shipment."""
    quote = ShipmentQuote.model_validate(quote_record.payload["quote"])
    evidence, policy_ids = policy_snapshot(session, principal, quote_record, origin)
    legal = check_eligibility(evidence, quote.product_id, quote.destination, origin, horizon_days)
    margin = calculate_margin(quote, origin)
    risks, risk_reasons = risk_snapshot(
        session, principal, quote.destination, origin, horizon_days, quote.synthetic
    )
    reasons = list(legal.reasons) + risk_reasons + margin["reasons"]
    if aware(quote_record.created_at) > origin:
        reasons.append("Private quotation/review was not yet available at decision origin")
    product = session.get(Product, quote.product_id)
    if product is None or len(product.hs_code) != 8:
        reasons.append("Exact source-supported 8-digit ITC mapping missing")
    review = quote_record.payload.get("review")
    if not review or datetime.fromisoformat(review["valid_until"]) < origin + timedelta(
        days=horizon_days
    ):
        reasons.append(
            "Quotation/capacity evidence lacks a current analyst review covering the window"
        )
    if quote.expires_at < origin + timedelta(days=horizon_days):
        reasons.append("Quotation expires before the end of the shipment window")
    seller_money = [quote.net_selling_price] + [
        line.money for line in quote.costs if line.payer == "seller"
    ]
    if any(money.expires_at < origin + timedelta(days=horizon_days) for money in seller_money):
        reasons.append("A selling/cost line expires before the end of the shipment window")
    for rate in quote.fx_rates:
        if rate.valid_until < origin + timedelta(days=horizon_days):
            reasons.append("FX quotation does not cover shipment window; hedge or re-quote")
    confidence = None
    if prediction is None:
        reasons.append("Product/destination/horizon prediction is missing")
    elif (
        prediction.product_id != quote.product_id
        or prediction.destination != quote.destination
        or prediction.horizon_days != horizon_days
        or aware(prediction.created_at) > origin
        or aware(prediction.forecast_origin) > origin
        or aware(prediction.forecast_origin) + timedelta(days=horizon_days) < origin
    ):
        reasons.append("Prediction scope, availability or validity does not match quotation")
    elif prediction.synthetic != quote.synthetic:
        reasons.append("Real and synthetic quotation/prediction provenance cannot be mixed")
    elif (
        prediction.demand_forecast is None
        or prediction.confidence is None
        or prediction.payload.get("model_validation_status") != "VALIDATED_OUT_OF_TIME"
        or prediction.payload.get("confidence_calibration_status") != "CALIBRATED_OUT_OF_TIME"
    ):
        reasons.append("Weekly demand and calibrated forecast confidence are unverified")
    else:
        confidence = float(prediction.confidence)
        if not 0 <= confidence <= 1:
            raise ValueError("Stored forecast confidence out of range")
        if prediction.demand_forecast < quote.shipment_tonnes:
            reasons.append(
                "Forecast demand below quoted shipment; verified buyer allocation/re-quote required"
            )
    if margin["profitable_on_quoted_assumptions"] is not True:
        reasons.append("Positive quoted margin is absent")
    components = review.get("normalized_components") if review else None
    if review and review.get("prediction_id") != (prediction.prediction_id if prediction else None):
        reasons.append("Normalized component review is not bound to this prediction")
    if components is None:
        reasons.append("Reviewed normalization of all score inputs is unavailable")
    elif confidence is not None and abs(components["confidence"] - confidence * 100) > 1e-6:
        reasons.append("Confidence score component differs from calibrated forecast confidence")
    gate = Eligibility(not reasons, tuple(sorted(set(reasons))))
    score = score_opportunity(gate, components)
    return {
        "status": score["status"],
        "opportunity_score": score["score"],
        "expected_margin_per_tonne": margin["expected_margin_per_tonne"],
        "expected_profit_per_shipment": margin["expected_profit_per_shipment"],
        "expected_margin_per_shipment": margin["expected_margin_per_shipment"],
        "currency": margin["currency"],
        "forecast_confidence": confidence,
        "horizon_days": horizon_days,
        "product_id": quote.product_id,
        "destination": quote.destination,
        "quote_id": quote_record.record_id,
        "quote_root_id": quote_record.payload.get("original_quote_id", quote_record.record_id),
        "demand_quantity_tonnes": str(prediction.demand_forecast)
        if prediction and confidence is not None
        else None,
        "prediction_id": prediction.prediction_id if prediction else None,
        "as_of": origin.astimezone(UTC).isoformat(),
        "policy_evidence_ids": policy_ids,
        "policy_evidence": [
            {
                "record_id": record_id,
                "category": item.category,
                "decision": item.decision,
                "source_url": item.source_url,
                "published_at": item.published_at.isoformat(),
                "verified_at": item.verified_at.isoformat() if item.verified_at else None,
                "effective_from": item.effective_from.isoformat(),
                "effective_to": item.effective_to.isoformat(),
            }
            for record_id, item in zip(policy_ids, evidence, strict=True)
        ],
        "country_risks": risks,
        "accounting": margin,
        "reasons": list(gate.reasons),
        "normalized_components": components,
        "normalization_reference": review.get("normalization_reference") if review else None,
        "synthetic": quote.synthetic,
        "label": "SYNTHETIC — ILLUSTRATIVE, NOT A LIVE SIGNAL"
        if quote.synthetic
        else "Conditional quotation assessment; verify again before quoting and shipment",
        "assumptions": [
            "No success claim follows from a transparent weighted score",
            "Policy reviews are human attestations against archived text, not automated legal clearance",
            "A country's import requirement alone does not establish Indian export viability",
        ],
        "next_actions": [
            "Resolve each listed evidence gap",
            "Reconfirm policies, counterparties and certificates",
            "Reconfirm stock, selling price, freight, FX and contract allocation before shipment",
        ],
    }
