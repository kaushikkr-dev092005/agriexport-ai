"""Explicit official HS2022 reference check; does not verify ITC(HS) or eligibility."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from src.ingestion.storage import archive


def main() -> None:
    """Verify each starter code exists, archive source and persist audit evidence."""
    url = "https://comtradeapi.un.org/files/v1/app/reference/H6.json"
    response = httpx.get(url, timeout=45)
    observed = datetime.now(UTC)
    digest, _ = archive(Path("data/raw"), response.content, url, observed)
    response.raise_for_status()
    body = response.json()
    if body.get("className") != "HS2022":
        raise ValueError("Unverified reference edition")
    reference = {row["id"]: row for row in body["results"]}
    target = Path("configs/products.json")
    products = json.loads(target.read_text())
    for product in products:
        if product["hs_revision"] != "HS2022":
            continue
        if product["hs_code"] not in reference:
            raise ValueError(f"Unknown HS2022 code: {product['hs_code']}")
        print(reference[product["hs_code"]]["text"])
    # Only after full verification: replace the incorrect initial HS2017 source link.
    for product in products:
        if product["hs_revision"] != "HS2022":
            continue
        product["source_url"] = url
        product["hs_code_status"] = "verified_code_exists_HS2022"
    target.write_text(json.dumps(products, indent=2) + "\n", encoding="utf-8")
    Path("configs/catalogue_verification.json").write_text(
        json.dumps(
            {
                "source_url": url,
                "retrieved_at": observed.isoformat(),
                "raw_sha256": digest,
                "edition": "HS2022",
                "codes_verified": [p["hs_code"] for p in products if p["hs_revision"] == "HS2022"],
                "itc_hs_8_digit": "unverified",
                "legal_eligibility": "unverified",
                "method": "code existence verified; display names are abbreviated category labels",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
