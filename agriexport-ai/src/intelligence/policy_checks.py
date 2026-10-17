"""Pure fail-closed gating over explicitly reviewed, point-in-time policy evidence."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class GateCategory(StrEnum):
    DGFT = "DGFT"
    DESTINATION_IMPORT = "DESTINATION_IMPORT"
    SPS_CERTIFICATION = "SPS_CERTIFICATION"
    SANCTIONS = "SANCTIONS"


@dataclass(frozen=True)
class PolicyEvidence:
    """Reviewed applicability for one product/destination and a bounded validity window."""

    category: GateCategory
    product_id: str
    destination: str
    decision: str
    published_at: datetime
    verified_at: datetime | None
    effective_from: datetime
    effective_to: datetime
    source_url: str

    def __post_init__(self) -> None:
        timestamps = [self.published_at, self.effective_from, self.effective_to]
        if self.verified_at:
            timestamps.append(self.verified_at)
        if any(t.tzinfo is None for t in timestamps) or self.effective_to < self.effective_from:
            raise ValueError("Bounded, timezone-aware policy validity required")
        if self.decision not in {"ALLOW", "BLOCK", "UNVERIFIED"}:
            raise ValueError("Unknown policy decision")
        if self.verified_at and self.verified_at < self.published_at:
            raise ValueError("Cannot verify a source before publication")
        if not self.source_url.startswith("https://"):
            raise ValueError("Official source link required")


@dataclass(frozen=True)
class Eligibility:
    """Hard gate output; no score may override its reasons."""

    eligible: bool
    reasons: tuple[str, ...]


def check_eligibility(
    evidence: list[PolicyEvidence],
    product_id: str,
    destination: str,
    origin: datetime,
    horizon_days: int,
) -> Eligibility:
    """Require all four categories to cover the complete shipping window as known then."""
    if origin.tzinfo is None or horizon_days not in {7, 14, 28}:
        raise ValueError("Timezone-aware origin and supported horizon required")
    end = origin + timedelta(days=horizon_days)
    applicable = [
        p
        for p in evidence
        if p.product_id == product_id and p.destination == destination and p.published_at <= origin
    ]
    reasons = []
    for category in GateCategory:
        known = [
            p
            for p in applicable
            if p.category == category and p.verified_at is not None and p.verified_at <= origin
        ]
        blocked = [
            p
            for p in known
            if p.decision == "BLOCK" and p.effective_from <= end and p.effective_to >= origin
        ]
        allowed = [
            p
            for p in known
            if p.decision == "ALLOW" and p.effective_from <= origin and p.effective_to >= end
        ]
        uncertain = [
            p
            for p in applicable
            if p.category == category
            and p.effective_from <= end
            and p.effective_to >= origin
            and (p.decision == "UNVERIFIED" or p.verified_at is None or p.verified_at > origin)
        ]
        if blocked:
            reasons.append(f"{category}: restriction applies within window")
        elif uncertain or not allowed:
            reasons.append(f"{category}: missing, expired, incomplete or unverified evidence")
    return Eligibility(not reasons, tuple(reasons))
