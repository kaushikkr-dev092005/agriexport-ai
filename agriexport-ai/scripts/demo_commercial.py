"""SYNTHETIC quotation accounting demo; no network, database or live recommendations."""

import json
from datetime import UTC, datetime, timedelta

from src.intelligence.policy_checks import check_eligibility
from src.ranking.opportunity_score import score_opportunity
from src.ranking.profitability import CORE_COSTS, CostCategory, ShipmentQuote, calculate_margin


def main() -> None:
    """Show explicitly hypothetical accounting alongside a blocked legal decision."""
    now = datetime.now(UTC)
    stamps = {"quoted_at": now, "published_at": now, "expires_at": now + timedelta(days=30)}

    def money(amount: str, basis: str = "per_tonne") -> dict:
        return {
            "amount": amount,
            "basis": basis,
            "currency": "USD",
            "evidence_reference": "SYNTHETIC illustrative quote including explicit zeroes",
            **stamps,
        }

    seller = CORE_COSTS | {CostCategory.FREIGHT, CostCategory.INSURANCE}
    costs = []
    for category in CostCategory:
        amount = (
            "500"
            if category == CostCategory.PROCUREMENT
            else "1000"
            if category == CostCategory.FREIGHT
            else "0"
        )
        costs.append(
            {
                "category": category,
                "payer": "seller" if category in seller else "buyer",
                "money": money(
                    amount, "per_shipment" if category == CostCategory.FREIGHT else "per_tonne"
                )
                if category in seller
                else None,
                "note": "SYNTHETIC explicit contract allocation",
            }
        )
    quote = ShipmentQuote.model_validate(
        {
            "product_id": "basmati_rice",
            "destination": "682",
            "incoterm": "CIF",
            "transport_mode": "sea",
            "named_place": "SYNTHETIC destination port",
            "shipment_tonnes": "20",
            "buyer_quantity_tonnes": "20",
            "verified_stock_tonnes": "20",
            "logistics_capacity_tonnes": "20",
            "capacity_evidence_reference": "SYNTHETIC capacity",
            "buyer_reference": "SYNTHETIC buyer",
            "logistics_reference": "SYNTHETIC carrier",
            "reporting_currency": "USD",
            "net_selling_price": money("1000"),
            "costs": costs,
            "contract_review_reference": "SYNTHETIC illustrative contract review",
            "synthetic": True,
            **stamps,
        }
    )
    gate = check_eligibility([], quote.product_id, quote.destination, now, 7)
    print(
        json.dumps(
            {
                "label": "SYNTHETIC — ILLUSTRATIVE, NOT A LIVE SIGNAL",
                "accounting": calculate_margin(quote, now),
                "decision": score_opportunity(gate, None),
                "forecast_confidence": None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
