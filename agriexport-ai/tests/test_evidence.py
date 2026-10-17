"""SYNTHETIC HTTP bodies test source boundaries, caching and availability, never legal approval."""

from pathlib import Path

import httpx
import pytest

from src.intelligence.evidence import DocumentFetcher

URL = "https://content.dgft.gov.in/SYNTHETIC"


def test_document_cache_retains_first_observed_vintage_and_checks_raw_integrity(tmp_path):
    calls = []

    def respond(request):
        calls.append(request.url)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><script>UNTRUSTED SCRIPT</script><p>SYNTHETIC policy text solely for parser and cache tests.</p></html>",
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetcher = DocumentFetcher(client, tmp_path, synthetic=True)
        original = fetcher.fetch(URL)
        cached = fetcher.fetch(URL)
        assert len(calls) == 1 and cached["published_at"] == original["published_at"]
        assert "UNTRUSTED SCRIPT" not in cached["text"]
        assert cached["interpretation_status"] == "UNVERIFIED" and cached["synthetic"]
        fetcher.fetch(URL, use_cache=False)
        assert len(calls) == 2
        Path(original["storage_path"]).write_text("SYNTHETIC corrupted raw response")
        with pytest.raises(ValueError, match="integrity"):
            fetcher.fetch(URL)
        with pytest.raises(ValueError, match="integrity"):
            fetcher.fetch(URL, use_cache=False)


@pytest.mark.parametrize("kind", ["redirect", "pdf", "rate_limit", "oversize"])
def test_documents_fail_closed_on_unverified_source_responses(tmp_path, kind):
    calls = []

    def respond(request):
        calls.append(request.url)
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        if kind == "pdf":
            return httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=b"SYNTHETIC"
            )
        if kind == "rate_limit":
            return httpx.Response(429, headers={"retry-after": "120"})
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"SYNTHETIC" * 120000
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises((ValueError, RuntimeError)):
            DocumentFetcher(client, tmp_path, synthetic=True).fetch(URL)
        assert len(calls) == 1
        assert not list((tmp_path / "cache").glob("*.json"))


@pytest.mark.parametrize(
    "url",
    [
        "http://content.dgft.gov.in/test",
        "https://localhost/test",
        "https://content.dgft.gov.in@localhost/test",
        "https://content.dgft.gov.in/test?secret=SYNTHETIC",
        "https://content.dgft.gov.in:8443/test",
    ],
)
def test_source_url_validation_precedes_network(tmp_path, url):
    def no_network(request):
        raise AssertionError("Rejected source must not perform a network request")

    with (
        httpx.Client(transport=httpx.MockTransport(no_network)) as client,
        pytest.raises(ValueError),
    ):
        DocumentFetcher(client, tmp_path, synthetic=True).fetch(url)
