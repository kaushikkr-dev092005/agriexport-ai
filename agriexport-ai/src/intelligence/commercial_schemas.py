"""Typed human-review inputs. LLM extraction cannot construct approved policy records."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from src.intelligence.policy_checks import GateCategory
from src.ranking.profitability import StrictModel


class PolicyReview(StrictModel):
    document_id: str
    rule_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    product_id: str
    country_code: str = Field(pattern=r"^\d{3}$")
    hs_code: str = Field(pattern=r"^\d{8}$")
    category: GateCategory
    decision: Literal["ALLOW", "BLOCK", "UNVERIFIED"]
    effective_from: datetime
    effective_to: datetime
    review_valid_until: datetime
    evidence_excerpt: str = Field(min_length=10, max_length=2000)
    review_notes: str = Field(min_length=10, max_length=2000)
    quote_id: str | None = None

    @model_validator(mode="after")
    def scope_and_dates(self) -> "PolicyReview":
        if self.effective_to < self.effective_from:
            raise ValueError("Invalid policy interval")
        if (
            self.category in {GateCategory.SANCTIONS, GateCategory.SPS_CERTIFICATION}
            and not self.quote_id
        ):
            raise ValueError(
                "Sanctions and shipment certifications require a quote-specific review"
            )
        return self


class RiskReview(StrictModel):
    document_id: str
    country_code: str = Field(pattern=r"^\d{3}$")
    indicator: Literal["payment", "logistics"]
    level: Literal["LOW", "MEDIUM", "HIGH", "UNVERIFIED"]
    valid_until: datetime
    evidence_excerpt: str = Field(min_length=10, max_length=2000)
    review_notes: str = Field(min_length=10, max_length=2000)


class QuoteReview(StrictModel):
    review_reference: str = Field(min_length=10, max_length=500)
    valid_until: datetime
    normalized_components: dict[str, float] | None = None
    prediction_id: str | None = None
    normalization_reference: str | None = None

    @model_validator(mode="after")
    def normalized_inputs(self) -> "QuoteReview":
        if self.normalized_components is not None:
            if (
                not self.prediction_id
                or not self.normalization_reference
                or len(self.normalization_reference) < 20
            ):
                raise ValueError(
                    "Reviewed components must bind a prediction and explain normalization"
                )
            from src.intelligence.policy_checks import Eligibility
            from src.ranking.opportunity_score import score_opportunity

            result = score_opportunity(Eligibility(True, ()), self.normalized_components)
            if result["score"] is None:
                raise ValueError("All normalized components are required")
        return self


class DocumentRequest(StrictModel):
    source_url: str
    force_refresh: bool = False


class ExtractionRequest(StrictModel):
    document_id: str
    query: str = Field(min_length=3, max_length=500)


class DecisionRequest(StrictModel):
    quote_id: str
    prediction_id: str | None = None
    horizon_days: Literal[7, 14, 28]
