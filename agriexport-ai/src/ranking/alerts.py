"""Material-change alerts compare dated decisions, with no invented or merged metrics."""

import hashlib
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import Principal
from src.database.commercial_models import CommercialDecision
from src.database.pilot_models import AlertRecord, AlertSubscription
from src.database.private_repository import append_record
from src.forecasting.service import aware


def material_changes(previous: dict | None, current: dict, preference: dict) -> list[str]:
    """Trigger only new eligible candidates, threshold crossings, quantity shifts or legal invalidation."""
    eligible = current.get("status") == "SCORED_WITH_UNVALIDATED_WEIGHTS"
    old_eligible = (
        previous is not None and previous.get("status") == "SCORED_WITH_UNVALIDATED_WEIGHTS"
    )
    changes = []
    if eligible and not old_eligible:
        changes.append("NEW_OPPORTUNITY")
    if (
        old_eligible
        and not eligible
        and any(
            str(reason).startswith(
                ("DGFT:", "DESTINATION_IMPORT:", "SPS_CERTIFICATION:", "SANCTIONS:")
            )
            for reason in current.get("reasons", [])
        )
    ):
        changes.append("POLICY_INVALIDATION")
    if previous and eligible:
        if current.get("currency") == previous.get("currency") == preference["currency"]:
            a, b = (
                previous.get("expected_margin_per_tonne"),
                current.get("expected_margin_per_tonne"),
            )
            if a is not None and b is not None:
                threshold = Decimal(str(preference["margin_threshold_per_tonne"]))
                if (Decimal(str(a)) >= threshold) != (Decimal(str(b)) >= threshold):
                    changes.append("MARGIN_THRESHOLD_CROSSED")
        a, b = previous.get("demand_quantity_tonnes"), current.get("demand_quantity_tonnes")
        if (
            a is not None
            and b is not None
            and Decimal(str(a)) > 0
            and abs(Decimal(str(b)) - Decimal(str(a))) / Decimal(str(a))
            >= Decimal(str(preference["forecast_shift_fraction"]))
        ):
            changes.append("LARGE_FORECAST_SHIFT")
    return changes


def emit_alerts(session: Session, principal: Principal, current: CommercialDecision) -> int:
    """Append one internal alert per material transition and subscription; caller owns transaction."""
    data = current.payload
    subscriptions = list(
        session.scalars(
            select(AlertSubscription)
            .where(
                AlertSubscription.tenant_id == principal.tenant_id,
                AlertSubscription.product_id == data["product_id"],
                AlertSubscription.destination == data["destination"],
                AlertSubscription.created_at <= current.created_at,
                AlertSubscription.synthetic == current.synthetic,
            )
            .order_by(AlertSubscription.created_at.desc(), AlertSubscription.record_id.desc())
        )
    )
    selected = {}
    for row in subscriptions:
        selected.setdefault((row.payload["horizon_days"], row.payload["currency"]), row)
    previous = None
    for candidate in session.scalars(
        select(CommercialDecision)
        .where(
            CommercialDecision.tenant_id == principal.tenant_id,
            CommercialDecision.created_at < current.created_at,
            CommercialDecision.synthetic == current.synthetic,
        )
        .order_by(CommercialDecision.created_at.desc(), CommercialDecision.record_id.desc())
    ):
        p = candidate.payload
        if (
            p.get("product_id"),
            p.get("destination"),
            p.get("horizon_days"),
            p.get("quote_root_id", candidate.quote_id),
        ) == (
            data["product_id"],
            data["destination"],
            data["horizon_days"],
            data.get("quote_root_id", current.quote_id),
        ):
            previous = candidate
            break
    count = 0
    for subscription in selected.values():
        preference = subscription.payload
        if (
            not preference["enabled"]
            or preference["horizon_days"] != data["horizon_days"]
            or preference["currency"] != data["currency"]
        ):
            continue
        for kind in material_changes(previous.payload if previous else None, data, preference):
            key = hashlib.sha256(
                json.dumps(
                    [
                        subscription.record_id,
                        previous.record_id if previous else None,
                        current.record_id,
                        kind,
                    ]
                ).encode()
            ).hexdigest()
            if session.scalar(
                select(AlertRecord.record_id).where(
                    AlertRecord.tenant_id == principal.tenant_id, AlertRecord.event_key == key
                )
            ):
                continue
            append_record(
                session,
                AlertRecord,
                principal,
                {
                    "kind": kind,
                    "delivery": "DASHBOARD_ONLY",
                    "decision_id": current.record_id,
                    "previous_decision_id": previous.record_id if previous else None,
                    "product_id": data["product_id"],
                    "destination": data["destination"],
                    "horizon_days": data["horizon_days"],
                    "currency": data["currency"],
                    "expected_margin_per_tonne": data.get("expected_margin_per_tonne"),
                    "opportunity_score": data.get("opportunity_score"),
                    "forecast_confidence": data.get("forecast_confidence"),
                    "open_risks": data.get("reasons", []),
                    "evidence": data.get("policy_evidence", []),
                    "as_of": data["as_of"],
                    "generated_at": aware(current.created_at).isoformat(),
                    "label": "SYNTHETIC — ILLUSTRATIVE, NOT A LIVE SIGNAL"
                    if current.synthetic
                    else "Conditional signal; verify before quoting",
                },
                "alert.material_change",
                current.synthetic,
                decision_id=current.record_id,
                event_key=key,
            )
            count += 1
    return count
