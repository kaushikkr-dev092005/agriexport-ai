"""Configurable transparent score: starting assumptions, never proof of export success."""

import math
from pathlib import Path

import yaml

from src.intelligence.policy_checks import Eligibility

COMPONENTS = frozenset({"demand", "indian_supply", "profit", "accessibility", "confidence"})


def load_weights(path: Path | None = None) -> dict[str, float]:
    """Load and validate the user-specified unvalidated weights."""
    weights = yaml.safe_load(
        (path or Path(__file__).resolve().parents[2] / "configs/scoring.yaml").read_text()
    )
    if set(weights) != COMPONENTS or any(
        isinstance(v, bool)
        or not isinstance(v, (float, int))
        or not math.isfinite(v)
        or not 0 <= v <= 1
        for v in weights.values()
    ):
        raise ValueError("Exact, finite, nonnegative scoring weights required")
    if not math.isclose(sum(weights.values()), 1, abs_tol=1e-9):
        raise ValueError("Scoring weights must sum to one")
    return weights


def score_opportunity(
    eligibility: Eligibility, components: dict[str, float] | None, weights_path: Path | None = None
) -> dict:
    """Gate before ranking; incomplete components never receive imputed zeroes."""
    if not eligibility.eligible:
        return {
            "score": None,
            "status": "BLOCKED_OR_UNVERIFIED",
            "reasons": list(eligibility.reasons),
        }
    if components is None or set(components) != COMPONENTS:
        return {
            "score": None,
            "status": "BLOCKED_OR_UNVERIFIED",
            "reasons": ["Complete verified score components unavailable"],
        }
    for value in components.values():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 100
        ):
            raise ValueError("Score components must be finite values in [0, 100]")
    weights = load_weights(weights_path)
    return {
        "score": sum(weights[key] * components[key] for key in COMPONENTS),
        "status": "SCORED_WITH_UNVALIDATED_WEIGHTS",
        "reasons": [],
        "notice": "Transparent score is not proof an export will succeed",
    }
