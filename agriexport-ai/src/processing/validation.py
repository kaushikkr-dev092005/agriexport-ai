"""Strict source-neutral observations. Availability is never inferred from period."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TradeRow(BaseModel):
    """One monthly, versioned trade observation with explicit provenance."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    product_id: str
    hs_code: str = Field(pattern=r"^\d{4}(\d{2})?(\d{2})?$")
    hs_revision: str
    reporter: str = Field(pattern=r"^\d{3}$")
    partner: str = Field(pattern=r"^\d{3}$")
    period: date
    event_date: date
    flow: Literal["X", "M"]
    quantity: Decimal = Field(ge=0, allow_inf_nan=False)
    quantity_unit: Literal["kg", "tonne"]
    value: Decimal = Field(ge=0, allow_inf_nan=False)
    currency: Literal["USD", "INR", "EUR", "GBP", "AED"]
    published_at: datetime
    retrieved_at: datetime
    availability_basis: Literal["source_publication", "first_observed"]
    publication_evidence_url: str | None = None
    source_url: str
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: str
    synthetic: bool = False

    @field_validator("product_id", "hs_revision", "revision")
    @classmethod
    def nonempty(cls, value: str) -> str:
        """Reject blank identities."""
        if not value:
            raise ValueError("identity must not be blank")
        return value

    @field_validator("source_url", "publication_evidence_url")
    @classmethod
    def source_link(cls, value: str | None) -> str | None:
        """Require reviewable HTTP(S) source links."""
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("source evidence must be an HTTP(S) URL")
        return value

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        """Reject ambiguous local timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def temporal_integrity(self) -> "TradeRow":
        """Enforce monthly observations and conservative availability."""
        if self.period.day != 1:
            raise ValueError("period must be the first day of the month")
        if (self.event_date.year, self.event_date.month) != (self.period.year, self.period.month):
            raise ValueError("event_date must belong to period")
        if self.event_date > self.published_at.date() or self.published_at > self.retrieved_at:
            raise ValueError("event_date <= published_at <= retrieved_at required")
        if self.availability_basis == "first_observed" and self.published_at != self.retrieved_at:
            raise ValueError("first_observed availability must equal retrieval time")
        if self.availability_basis == "source_publication" and not self.publication_evidence_url:
            raise ValueError("historical publication requires evidence")
        return self

    @property
    def quantity_tonnes(self) -> Decimal:
        """Convert mass; never convert value currencies implicitly."""
        return self.quantity / 1000 if self.quantity_unit == "kg" else self.quantity
