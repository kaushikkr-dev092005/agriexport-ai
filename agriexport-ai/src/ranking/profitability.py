"""Decimal-based quote accounting with explicit units, FX vintages and Incoterm allocation."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Currency = Literal["INR", "USD", "EUR", "GBP", "AED", "SAR", "CNY", "JPY"]


class StrictModel(BaseModel):
    """Reject unexpected quantitative fields and ambiguous timestamps."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="after")
    @classmethod
    def aware_time(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("Timezone required")
            return value.astimezone(UTC)
        return value


class CostCategory(StrEnum):
    PROCUREMENT = "procurement"
    PROCESSING = "processing"
    PACKAGING = "packaging"
    CERTIFICATION = "certification"
    INLAND_TRANSPORT = "inland_transport"
    ORIGIN_PORT = "origin_port"
    EXPORT_CLEARANCE = "export_clearance"
    FREIGHT = "freight"
    INSURANCE = "insurance"
    DESTINATION_TRANSPORT = "destination_transport"
    IMPORT_CLEARANCE = "import_clearance"
    DUTIES = "duties"
    TAXES = "taxes"
    UNLOADING = "unloading"
    FINANCING = "financing"
    OTHER = "other"


CORE_COSTS = frozenset(
    {
        CostCategory.PROCUREMENT,
        CostCategory.PROCESSING,
        CostCategory.PACKAGING,
        CostCategory.CERTIFICATION,
        CostCategory.INLAND_TRANSPORT,
        CostCategory.ORIGIN_PORT,
        CostCategory.EXPORT_CLEARANCE,
        CostCategory.FINANCING,
        CostCategory.OTHER,
    }
)


class Money(StrictModel):
    """Quoted amount with an unambiguous mass/shipment basis."""

    amount: Decimal = Field(ge=0, allow_inf_nan=False)
    currency: Currency
    basis: Literal["per_kg", "per_tonne", "per_shipment"]
    evidence_reference: str = Field(min_length=1, max_length=500)
    quoted_at: datetime
    published_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def quotation_dates(self) -> "Money":
        if not self.quoted_at <= self.published_at <= self.expires_at:
            raise ValueError("Money quote event <= availability <= expiry required")
        return self


class CostLine(StrictModel):
    category: CostCategory
    payer: Literal["seller", "buyer"]
    money: Money | None = None
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def no_unknown_seller_amount(self) -> "CostLine":
        if self.payer == "seller" and self.money is None:
            raise ValueError(
                "Seller-paid costs need an explicit amount, including documented zeroes"
            )
        return self


class FxRate(StrictModel):
    """Quote-currency units per base-currency unit; no implicit inversion or triangulation."""

    base_currency: Currency
    quote_currency: Currency
    rate: Decimal = Field(gt=0, allow_inf_nan=False)
    rate_date: date
    published_at: datetime
    valid_until: datetime
    source_url: str = Field(pattern=r"^https://", max_length=2048)
    verified: bool

    @model_validator(mode="after")
    def rate_dates(self) -> "FxRate":
        if self.base_currency == self.quote_currency:
            raise ValueError("Identity conversion needs no market FX quote")
        if self.rate_date > self.published_at.date() or self.valid_until < self.published_at:
            raise ValueError("Invalid FX availability/date interval")
        return self


class ShipmentQuote(StrictModel):
    """A fixed-size quotation. A smaller feasible shipment requires re-quotation."""

    product_id: str = Field(min_length=1, max_length=80)
    destination: str = Field(pattern=r"^\d{3}$")
    incoterm: Literal["FOB", "CFR", "CIF", "DAP", "DDP"]
    transport_mode: Literal["sea", "air", "road", "rail"]
    named_place: str = Field(min_length=1, max_length=200)
    shipment_tonnes: Decimal = Field(gt=0, allow_inf_nan=False)
    buyer_quantity_tonnes: Decimal = Field(ge=0, allow_inf_nan=False)
    verified_stock_tonnes: Decimal = Field(ge=0, allow_inf_nan=False)
    logistics_capacity_tonnes: Decimal = Field(ge=0, allow_inf_nan=False)
    capacity_evidence_reference: str = Field(min_length=1, max_length=500)
    buyer_reference: str = Field(min_length=1, max_length=200)
    logistics_reference: str = Field(min_length=1, max_length=200)
    reporting_currency: Currency
    net_selling_price: Money
    costs: list[CostLine]
    fx_rates: list[FxRate] = Field(default_factory=list)
    quoted_at: datetime
    published_at: datetime
    expires_at: datetime
    contract_review_reference: str = Field(min_length=1, max_length=500)
    synthetic: bool = False

    @model_validator(mode="after")
    def quote_integrity(self) -> "ShipmentQuote":
        if not self.quoted_at <= self.published_at <= self.expires_at:
            raise ValueError("Quote event <= availability <= expiry required")
        if self.incoterm in {"FOB", "CFR", "CIF"} and self.transport_mode != "sea":
            raise ValueError(
                "FOB/CFR/CIF accounting supports sea shipments only; use a suitable term"
            )
        categories = [line.category for line in self.costs]
        if len(categories) != len(set(categories)) or set(categories) != set(CostCategory):
            raise ValueError(
                "Every cost category must appear exactly once; no hidden omitted costs"
            )
        seller = set(CORE_COSTS)
        if self.incoterm != "FOB":
            seller.add(CostCategory.FREIGHT)
        if self.incoterm == "CIF":
            seller.add(CostCategory.INSURANCE)
        if self.incoterm in {"DAP", "DDP"}:
            seller.add(CostCategory.DESTINATION_TRANSPORT)
        if self.incoterm == "DDP":
            seller.update({CostCategory.IMPORT_CLEARANCE, CostCategory.DUTIES, CostCategory.TAXES})
        for line in self.costs:
            # Nonmandatory insurance is an explicit commercial choice, not an assumed zero.
            if line.category == CostCategory.INSURANCE and self.incoterm != "CIF":
                continue
            expected = "seller" if line.category in seller else "buyer"
            if line.payer != expected:
                raise ValueError(
                    f"{self.incoterm} allocation conflicts for {line.category}; review contract/requote"
                )
        pairs = [(fx.base_currency, fx.quote_currency) for fx in self.fx_rates]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Ambiguous duplicate FX quotes")
        return self


def calculate_margin(quote: ShipmentQuote, as_of: datetime) -> dict:
    """Account for a quoted shipment at the timestamp; legal eligibility is independent."""
    if as_of.tzinfo is None:
        raise ValueError("as_of requires timezone")
    reasons = []
    if not quote.published_at <= as_of <= quote.expires_at:
        reasons.append("Quotation unavailable or expired at decision time")
    feasible = min(
        quote.shipment_tonnes,
        quote.buyer_quantity_tonnes,
        quote.verified_stock_tonnes,
        quote.logistics_capacity_tonnes,
    )
    if feasible < quote.shipment_tonnes:
        reasons.append(
            "Buyer/stock/logistics capacity below quoted shipment; re-quotation required"
        )
    conversions = []

    def per_tonne(money: Money) -> Decimal | None:
        if not money.published_at <= as_of <= money.expires_at:
            reasons.append("A selling/cost quotation is unavailable or expired at decision time")
            return None
        amount = money.amount * 1000 if money.basis == "per_kg" else money.amount
        if money.basis == "per_shipment":
            amount /= quote.shipment_tonnes
        if money.currency != quote.reporting_currency:
            rates = [
                r
                for r in quote.fx_rates
                if r.base_currency == money.currency
                and r.quote_currency == quote.reporting_currency
                and r.verified
                and r.published_at <= as_of <= r.valid_until
                and r.rate_date <= as_of.date()
            ]
            if len(rates) != 1:
                reasons.append(
                    f"Verified available FX {money.currency}/{quote.reporting_currency} missing"
                )
                return None
            fx = rates[0]
            amount *= fx.rate
            evidence = fx.model_dump(mode="json")
            if evidence not in conversions:
                conversions.append(evidence)
        return amount

    selling = per_tonne(quote.net_selling_price)
    cost_values = []
    breakdown = []
    for line in quote.costs:
        amount = per_tonne(line.money) if line.payer == "seller" else None
        if amount is not None:
            cost_values.append(amount)
        breakdown.append(
            {
                "category": line.category.value,
                "payer": line.payer,
                "seller_cost_per_tonne": str(amount) if amount is not None else None,
                "evidence_reference": line.money.evidence_reference if line.money else line.note,
            }
        )
    ready = not reasons and selling is not None
    total = sum(cost_values, Decimal(0)) if ready else None
    margin = selling - total if ready else None
    return {
        "status": "CALCULATED_FROM_QUOTATIONS" if ready else "NOT_CALCULATED",
        "currency": quote.reporting_currency,
        "incoterm": quote.incoterm,
        "named_place": quote.named_place,
        "quoted_shipment_tonnes": str(quote.shipment_tonnes),
        "feasible_quantity_tonnes": str(feasible),
        "net_selling_price_per_tonne": str(selling) if ready else None,
        "total_seller_cost_per_tonne": str(total) if total is not None else None,
        "expected_margin_per_tonne": str(margin) if margin is not None else None,
        "expected_profit_per_shipment": str(margin * quote.shipment_tonnes)
        if margin is not None
        else None,
        "expected_margin_per_shipment": str(margin * quote.shipment_tonnes)
        if margin is not None
        else None,
        "profitable_on_quoted_assumptions": margin > 0 if margin is not None else None,
        "cost_breakdown": breakdown,
        "fx_evidence": conversions,
        "reasons": sorted(set(reasons)),
        "synthetic": quote.synthetic,
        "label": "SYNTHETIC — ILLUSTRATIVE, NOT A LIVE SIGNAL"
        if quote.synthetic
        else "Quotation calculation; eligibility and execution require separate verification",
        "assumptions": [
            "Net selling quote already reflects discounts; financing/taxes are explicit cost lines",
            "Fixed quoted shipment size; no extrapolation to smaller shipments",
            "FX validity and quote basis are supplied evidence, not predicted exchange rates",
            "Incoterm allocations are a supported accounting template requiring contract review",
        ],
    }
