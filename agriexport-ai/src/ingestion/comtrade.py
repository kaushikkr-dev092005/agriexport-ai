"""Conservative Comtrade preview connector: first-observed availability, no completeness claim."""

import calendar
import hashlib
import json
import logging
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.ingestion.storage import archive
from src.processing.validation import TradeRow

logger = logging.getLogger(__name__)


class RetryableSourceError(Exception):
    """Transient source response; retry conservatively."""


class ComtradeConnector:
    """Inject client, credentials and storage; serial requests respect Retry-After."""

    def __init__(
        self,
        client: httpx.Client,
        raw_root: Path,
        api_key: str = "",
        base_url: str = "https://comtradeapi.un.org/public/v1/preview/C/M/HS",
        min_interval_seconds: float = 2.0,
        synthetic: bool = False,
    ):
        self.client, self.raw_root, self.api_key = client, raw_root, api_key
        self.base_url = base_url
        self.min_interval = min_interval_seconds
        self.last_request = 0.0
        self.synthetic = synthetic

    def fetch(
        self,
        reporter: str,
        partner: str,
        hs_code: str,
        period: str,
        flow: str = "X",
        use_cache: bool = True,
    ) -> tuple[dict, str, Path, datetime]:
        """Cache by query for 24h. Fail on preview cap; never imply paginated completeness."""
        if not (len(period) == 6 and period.isdigit()):
            raise ValueError("Monthly period must be YYYYMM")
        date(int(period[:4]), int(period[4:]), 1)
        params = {
            "reporterCode": reporter,
            "partnerCode": partner,
            "cmdCode": hs_code,
            "period": period,
            "flowCode": flow,
            "maxRecords": 500,
            "partner2Code": "0",
            "customsCode": "C00",
            "motCode": "0",
        }
        source_url = str(httpx.URL(self.base_url, params=params))
        cache_id = hashlib.sha256((source_url + str(self.synthetic)).encode()).hexdigest()
        cache = self.raw_root / "cache" / f"{cache_id}.json"
        now = datetime.now(UTC)
        if use_cache and cache.exists():
            entry = json.loads(cache.read_text())
            observed = datetime.fromisoformat(entry["retrieved_at"])
            if now - observed < timedelta(hours=24):
                raw = self.raw_root / f"{entry['sha256']}.raw"
                payload = raw.read_bytes()
                if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                    raise ValueError("Cache integrity failure")
                return json.loads(payload), source_url, raw, observed
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=1, max=8),
            retry=retry_if_exception_type((httpx.TransportError, RetryableSourceError)),
            reraise=True,
        ):
            with attempt:
                time.sleep(max(0, self.min_interval - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                response = self.client.get(
                    self.base_url,
                    params=params,
                    headers={"Ocp-Apim-Subscription-Key": self.api_key} if self.api_key else {},
                )
                now = datetime.now(UTC)
                _, raw = archive(self.raw_root, response.content, source_url, now, self.synthetic)
                if response.status_code == 429:
                    # Do not retry before a long server window or sleep indefinitely.
                    raise RuntimeError(
                        "Comtrade rate limited; Retry-After="
                        + response.headers.get("Retry-After", "unverified")
                    )
                if response.status_code >= 500:
                    raise RetryableSourceError(f"Comtrade HTTP {response.status_code}")
                response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise TypeError("Unverified Comtrade response schema")
        if body.get("error") or len(body["data"]) >= 500:
            raise ValueError("Source error or potentially truncated preview; narrow query")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"sha256": raw.stem, "retrieved_at": now.isoformat()}))
        logger.info("Archived Comtrade response: %d rows", len(body["data"]))
        return body, source_url, raw, now


def normalize(
    body: dict,
    product_id: str,
    source_url: str,
    raw: Path,
    retrieved_at: datetime,
    synthetic: bool = False,
) -> list[TradeRow]:
    """Use netWgt in kg, primaryValue in USD; reject unknown classification revisions."""
    rows = []
    for data in body["data"]:
        if data.get("classificationCode") != "H6":
            raise ValueError("Only reviewed H6 / HS2022 mapping supported")
        if data.get("isAggregate") is True and len(str(data.get("cmdCode", ""))) > 6:
            raise ValueError("Unexpected aggregate detail")
        year, month = int(data["refYear"]), int(data["refMonth"])
        if str(data["period"]) != f"{year}{month:02d}":
            raise ValueError("Comtrade period mismatch")
        if data.get("netWgt") is None or data.get("primaryValue") is None:
            raise ValueError("Missing netWgt or primaryValue; quantity/value not calculated")
        if data.get("isNetWgtEstimated"):
            raise ValueError("Estimated source mass requires a reviewed quality policy; unverified")
        rows.append(
            TradeRow(
                product_id=product_id,
                hs_code=str(data["cmdCode"]),
                hs_revision="HS2022",
                reporter=str(data["reporterCode"]).zfill(3),
                partner=str(data["partnerCode"]).zfill(3),
                period=date(year, month, 1),
                event_date=date(year, month, calendar.monthrange(year, month)[1]),
                flow=data["flowCode"],
                quantity=data["netWgt"],
                quantity_unit="kg",
                value=data["primaryValue"],
                currency="USD",
                published_at=retrieved_at,
                retrieved_at=retrieved_at,
                availability_basis="first_observed",
                source_url=source_url,
                raw_sha256=raw.stem,
                revision=raw.stem,
                synthetic=synthetic,
            )
        )
    return rows
