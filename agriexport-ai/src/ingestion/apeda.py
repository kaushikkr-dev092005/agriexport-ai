"""Reviewed APEDA / Commerce CSV handoff. No undocumented scraping API is assumed."""

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Literal

from src.ingestion.storage import archive
from src.processing.validation import TradeRow


def load_indian_csv(
    path: Path,
    source_url: str,
    retrieved_at: datetime,
    raw_root: Path,
    source: Literal["apeda", "commerce"],
) -> tuple[list[TradeRow], Path]:
    """Import canonical CSV, preserving original bytes and rejecting ambiguous units.

    An operator must map downloaded source headings to the documented canonical schema.
    Never assign historical publication dates without source evidence.
    """
    allowed_host = "agriexchange.apeda.gov.in" if source == "apeda" else "tradestat.commerce.gov.in"
    from urllib.parse import urlparse

    if urlparse(source_url).hostname != allowed_host:
        raise ValueError("Source URL does not match selected official source")
    payload = path.read_bytes()
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("Missing or duplicate CSV headings")
    records = list(reader)
    digest, stored = archive(
        raw_root,
        payload,
        source_url,
        retrieved_at,
        synthetic=any(str(r.get("synthetic")).lower() == "true" for r in records),
    )
    rows = []
    for index, data in enumerate(records, start=2):
        try:
            if data.get("reporter") != "356" or data.get("flow") != "X":
                raise ValueError("Indian export import requires reporter 356 and flow X")
            data.update(source_url=source_url, raw_sha256=digest, retrieved_at=retrieved_at)
            if not data.get("published_at"):
                data.update(published_at=retrieved_at, availability_basis="first_observed")
            if not data.get("publication_evidence_url"):
                data["publication_evidence_url"] = None
            rows.append(TradeRow.model_validate(data))
        except (ValueError, TypeError) as error:
            raise ValueError(f"CSV row {index}: {error}") from error
    if not rows:
        raise ValueError("Empty CSV")
    return rows, stored
