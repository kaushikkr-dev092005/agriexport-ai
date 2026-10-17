"""SYNTHETIC native source fixtures, exercising real-format temporal/unit pitfalls."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from src.ingestion.commerce import CommerceConnector, Report, normalize_reports, parse_report
from src.ingestion.storage import archive

PERIOD = date(2025, 1, 1)
OBSERVED = datetime(2025, 3, 1, tzinfo=UTC)


def synthetic_html(
    report: str, unit: str = "KGS", heading: str = "Jan-2025 (R)", value: str | None = None
) -> bytes:
    """SYNTHETIC values deliberately differ from previous-year and cumulative columns."""
    basis = "Quantity" if report == "2" else "US $ Million"
    number = value if value is not None else ("2,000" if report == "2" else "0.01")
    return f"""<html><p>SYNTHETIC</p><p><b>Commodity: 10063020 *BASMATI RICE Unit: {unit}</b></p>
      <p>Values in {basis}</p><table><tr><th>S.No.</th><th>Country</th><th>Jan-2024 (R)</th>
      <th>{heading}</th><th>%Growth</th><th>Jan-Jan2024 (R)</th>
      <th>Jan-Jan2025 (R)</th><th>%Growth</th></tr>
      <tr><td>1</td><td>SAUDI ARAB</td><td>999</td><td>{number}</td><td>0</td>
      <td>99999</td><td>88888</td><td>0</td></tr></table></html>""".encode()


def document(root: Path, report: str) -> Report:
    payload = synthetic_html(report)
    _, raw = archive(root, payload, "https://example.org/SYNTHETIC", OBSERVED, True)
    return Report(payload, raw, OBSERVED, True)


def test_native_normalization_units_scale_and_publication(tmp_path):
    rows, bundle = normalize_reports(
        document(tmp_path, "2"),
        document(tmp_path, "1"),
        "basmati_rice",
        "10063020",
        PERIOD,
        ["682"],
        tmp_path,
    )
    assert rows[0].synthetic
    assert rows[0].quantity_tonnes == Decimal(2)
    assert rows[0].value == Decimal(10000)
    assert rows[0].currency == "USD"
    assert rows[0].published_at == OBSERVED
    assert rows[0].availability_basis == "first_observed"
    assert "quantity_sha256" in bundle.read_text()


@pytest.mark.parametrize(
    "change",
    [
        {"unit": ""},
        {"unit": "quintal"},
        {"heading": "Jan-Jan2025 (R)"},
        {"heading": "Feb-2025 (R)"},
        {"value": "-"},
        {"value": "NaN"},
        {"value": "-1"},
    ],
)
def test_ambiguous_or_wrong_scope_reports_rejected(change):
    with pytest.raises(ValueError):
        parse_report(synthetic_html("2", **change), "10063020", PERIOD, "2")


def test_response_scope_and_currency_rejected():
    with pytest.raises(ValueError, match="HS code"):
        parse_report(synthetic_html("2"), "1006", PERIOD, "2")
    with pytest.raises(ValueError, match="currency"):
        parse_report(
            synthetic_html("1").replace(b"US $ Million", b"INR Crore"), "10063020", PERIOD, "1"
        )


def test_native_transport_cache_and_fresh_token(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, text='<input name="_token" value="SYNTHETIC-token">')
        return httpx.Response(200, content=synthetic_html("2"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        connector = CommerceConnector(client, tmp_path, 0, synthetic=True)
        first = connector.fetch("10063020", PERIOD, "2")
        second = connector.fetch("10063020", PERIOD, "2")
    assert calls == ["GET", "POST"]
    assert first.retrieved_at == second.retrieved_at and first.raw == second.raw


def test_missing_source_country_is_not_zero(tmp_path):
    with pytest.raises(ValueError, match="country"):
        normalize_reports(
            document(tmp_path, "2"),
            document(tmp_path, "1"),
            "basmati_rice",
            "10063020",
            PERIOD,
            ["840"],
            tmp_path,
        )


def test_session_failure_retried_with_new_form(tmp_path):
    posts = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text='<input name="_token" value="SYNTHETIC-token">')
        posts.append(request)
        return (
            httpx.Response(419)
            if len(posts) == 1
            else httpx.Response(200, content=synthetic_html("2"))
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        CommerceConnector(client, tmp_path, 0, synthetic=True).fetch("10063020", PERIOD, "2")
    assert len(posts) == 2
