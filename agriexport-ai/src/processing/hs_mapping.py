"""Versioned HS catalogue; headings are not legal ITC(HS) eligibility mappings."""

import json
from pathlib import Path

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "configs" / "products.json"


def catalogue() -> list[dict]:
    """Load catalogue without mutable module state."""
    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


def validate_mapping(product_id: str, hs_code: str, hs_revision: str) -> None:
    """Accept only an exact reviewed catalogue level/revision; never guess finer detail."""
    if not any(
        p["product_id"] == product_id
        and p["hs_code"] == hs_code
        and p["hs_revision"] == hs_revision
        for p in catalogue()
    ):
        raise ValueError("HS mapping unverified: exact catalogue mapping required")
