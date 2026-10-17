"""Native read-only Commerce MEIDB form reports, with explicit units and source vintages."""

import calendar
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.ingestion.storage import archive
from src.processing.hs_mapping import validate_mapping
from src.processing.validation import TradeRow

URL = "https://tradestat.commerce.gov.in/meidb/commodity_wise_all_countries_export"
COUNTRY_LABELS = {
    "682": "SAUDI ARAB",
    "840": "U S A",
    "784": "U ARAB EMTS",
    "826": "U K",
    "528": "NETHERLAND",
    "050": "BANGLADESH",
    "144": "SRI LANKA",
}


class TransientReportError(Exception):
    """Temporary source/server/session failure eligible for a fresh read request."""


@dataclass(frozen=True)
class Report:
    """One immutable official response and its availability timestamp."""

    payload: bytes
    raw: Path
    retrieved_at: datetime
    synthetic: bool = False


class CommerceConnector:
    """Fetch official report forms serially; no login or challenge circumvention."""

    def __init__(
        self,
        client: httpx.Client,
        raw_root: Path,
        min_interval_seconds: float = 2,
        synthetic: bool = False,
    ):
        self.client, self.raw_root = client, raw_root
        self.interval, self.synthetic = min_interval_seconds, synthetic
        self.last_request = 0.0

    def fetch(self, hs_code: str, period: date, report_type: str, use_cache: bool = True) -> Report:
        """Read one explicit product/month report; cache retains original availability."""
        if not re.fullmatch(r"\d{4}(\d{2})?(\d{2})?", hs_code) or period.day != 1:
            raise ValueError("Exact HS code and first-of-month period required")
        if report_type not in {"1", "2"}:
            raise ValueError("Only USD-million value (1) and quantity (2) supported")
        parameters = {
            "cwacexHSCODE": hs_code,
            "cwacexMonth": str(period.month),
            "cwacexYear": str(period.year),
            "cwacexReportVal": report_type,
            "cwacexReportYear": "2",
        }
        cache_key = hashlib.sha256(
            json.dumps([parameters, self.synthetic], sort_keys=True).encode()
        ).hexdigest()
        cache = self.raw_root / "cache" / f"commerce-{cache_key}.json"
        if use_cache and cache.exists():
            entry = json.loads(cache.read_text())
            observed = datetime.fromisoformat(entry["retrieved_at"])
            if datetime.now(UTC) - observed < timedelta(hours=24):
                raw = self.raw_root / (entry["sha256"] + ".raw")
                payload = raw.read_bytes()
                if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                    raise ValueError("Commerce cache integrity failure")
                return Report(payload, raw, observed, self.synthetic)
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=1, max=8),
            retry=retry_if_exception_type((httpx.TransportError, TransientReportError)),
            reraise=True,
        ):
            with attempt:
                time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                form = self.client.get(URL)
                form.raise_for_status()
                token = BeautifulSoup(form.text, "html.parser").select_one('input[name="_token"]')
                if token is None:
                    raise ValueError("Official Commerce form changed; token unavailable")
                response = self.client.post(URL, data={**parameters, "_token": token["value"]})
                observed = datetime.now(UTC)
                _, raw = archive(self.raw_root, response.content, URL, observed, self.synthetic)
                if response.status_code == 429:
                    raise RuntimeError(
                        "Commerce rate limited; Retry-After="
                        + response.headers.get("Retry-After", "unverified")
                    )
                if response.status_code == 419 or response.status_code >= 500:
                    raise TransientReportError(f"Commerce HTTP {response.status_code}")
                response.raise_for_status()
        # Check scope/unit before allowing the response into the success cache.
        parse_report(response.content, hs_code, period, report_type)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps(
                {
                    "sha256": raw.stem,
                    "retrieved_at": observed.isoformat(),
                    "request_parameters": parameters,
                }
            )
        )
        return Report(response.content, raw, observed, self.synthetic)


def parse_report(
    payload: bytes, hs_code: str, period: date, report_type: str
) -> dict[str, Decimal]:
    """Read the exact month's column; never use cumulative or previous-year values."""
    soup = BeautifulSoup(payload.decode("utf-8"), "html.parser")
    label = soup.find(string=lambda text: text and "Commodity:" in text)
    header = " ".join(label.parent.get_text(" ", strip=True).split()) if label else ""
    match = re.fullmatch(r"Commodity:\s*(\d+)\s+(.+?)\s+Unit:\s*(.*)", header)
    if not match or match[1] != hs_code:
        raise ValueError("Report HS code/header does not match request")
    if report_type == "2" and match[3] != "KGS":
        raise ValueError("Quantity unit missing or unverified; not calculated")
    text = " ".join(soup.get_text(" ", strip=True).split())
    basis = "Values in Quantity" if report_type == "2" else "Values in US $ Million"
    if basis not in text:
        raise ValueError("Report value/currency basis unverified")
    tables = [t for t in soup.select("table") if "Country" in t.get_text()]
    if len(tables) != 1:
        raise ValueError("Expected one product-country trade table")
    rows = tables[0].select("tr")
    headings = [" ".join(c.get_text(" ", strip=True).split()) for c in rows[0].select("th,td")]
    if len(headings) != 8 or headings[:2] != ["S.No.", "Country"]:
        raise ValueError("Commerce table schema changed")
    month_name = calendar.month_abbr[period.month]
    if not re.fullmatch(rf"{month_name}-{period.year}(?: \([RF]\))?", headings[3]):
        raise ValueError("Requested month/year column absent; no cumulative substitution")
    result = {}
    for row in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in row.select("td")]
        if not cells:
            continue
        if any("Total" == value or "TOTAL" == value for value in cells):
            continue
        if len(cells) != 8:
            raise ValueError("Unexpected Commerce row width")
        country = " ".join(cells[1].split())
        if country in result:
            raise ValueError("Duplicate country row")
        # A dash is missing information, never zero.
        try:
            value = Decimal(cells[3].replace(",", ""))
        except InvalidOperation as error:
            raise ValueError(f"Missing/invalid trade value for {country}") from error
        if not value.is_finite() or value < 0:
            raise ValueError("Invalid quantity/value")
        result[country] = value
    if not result:
        raise ValueError("No country observations returned")
    return result


def normalize_reports(
    quantity: Report,
    value: Report,
    product_id: str,
    hs_code: str,
    period: date,
    partners: list[str],
    raw_root: Path,
) -> tuple[list[TradeRow], Path]:
    """Join quantities and values by exact source country label; archive both-parent lineage.

    ITC-source means a code observed in the official report, not a verified edition or
    permission to export. Value precision remains the source's rounded USD million basis.
    """
    validate_mapping(product_id, hs_code, "ITC-source")
    quantities = parse_report(quantity.payload, hs_code, period, "2")
    values = parse_report(value.payload, hs_code, period, "1")
    if set(quantities) != set(values):
        raise ValueError("Quantity/value country coverage differs")
    if quantity.synthetic != value.synthetic:
        raise ValueError("Mixed synthetic and real source documents")
    observed = max(quantity.retrieved_at, value.retrieved_at)
    bundle = {
        "source_url": URL,
        "hs_code": hs_code,
        "period": period.isoformat(),
        "quantity_sha256": quantity.raw.stem,
        "value_sha256": value.raw.stem,
        "quantity_retrieved_at": quantity.retrieved_at.isoformat(),
        "value_retrieved_at": value.retrieved_at.isoformat(),
        "value_basis": "USD million, rounded by source; scaled to USD",
        "synthetic": quantity.synthetic,
        "hs_edition": "unverified",
    }
    digest, raw = archive(
        raw_root, json.dumps(bundle, sort_keys=True).encode(), URL, observed, quantity.synthetic
    )
    output = []
    for partner in partners:
        label = COUNTRY_LABELS.get(partner)
        if not label or label not in quantities:
            raise ValueError(f"Source country mapping/observation unverified: {partner}")
        output.append(
            TradeRow(
                product_id=product_id,
                hs_code=hs_code,
                hs_revision="ITC-source",
                reporter="356",
                partner=partner,
                period=period,
                event_date=date(
                    period.year, period.month, calendar.monthrange(period.year, period.month)[1]
                ),
                flow="X",
                quantity=quantities[label],
                quantity_unit="kg",
                value=values[label] * Decimal(1_000_000),
                currency="USD",
                published_at=observed,
                retrieved_at=observed,
                availability_basis="first_observed",
                source_url=URL,
                raw_sha256=digest,
                revision=digest,
                synthetic=quantity.synthetic,
            )
        )
    return output, raw
