"""Small explicit live format probe. Archives evidence, never invents observations."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from src.ingestion.storage import archive


def main() -> None:
    """Inspect two official Commerce reports and one minimal Comtrade query."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hs", default="10063020")
    parser.add_argument("--comtrade", action="store_true")
    args = parser.parse_args()
    url = "https://tradestat.commerce.gov.in/meidb/commodity_wise_all_countries_export"
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        for report in ("2", "1"):
            page = client.get(url)
            page.raise_for_status()
            soup = BeautifulSoup(page.text, "html.parser")
            token = soup.select_one('input[name="_token"]')
            if token is None:
                raise ValueError("Official report form changed")
            response = client.post(
                url,
                data={
                    "_token": token["value"],
                    "cwacexMonth": "1",
                    "cwacexYear": "2025",
                    "cwacexReportVal": report,
                    "cwacexReportYear": "2",
                    "cwacexHSCODE": args.hs,
                },
            )
            observed = datetime.now(UTC)
            digest, raw = archive(Path("data/raw"), response.content, url, observed)
            response.raise_for_status()
            Path(f"data/probes/commerce-{report}.html").write_bytes(response.content)
            parsed = BeautifulSoup(response.text, "html.parser")
            tables = [
                [
                    [c.get_text(" ", strip=True) for c in row.select("th,td")]
                    for row in table.select("tr")[:5]
                ]
                for table in parsed.select("table")
            ]
            print(
                json.dumps(
                    {
                        "source": "commerce",
                        "report": report,
                        "sha256": digest,
                        "raw": str(raw),
                        "tables": tables,
                    }
                )
            )
        if not args.comtrade:
            return
        response = client.get(
            "https://comtradeapi.un.org/public/v1/preview/C/M/HS",
            params={
                "reporterCode": 356,
                "partnerCode": 682,
                "cmdCode": "1006",
                "period": "202401",
                "flowCode": "X",
                "maxRecords": 10,
            },
        )
        digest, _ = archive(
            Path("data/raw"), response.content, str(response.url), datetime.now(UTC)
        )
        print(
            json.dumps(
                {
                    "source": "comtrade_minimal",
                    "status": response.status_code,
                    "sha256": digest,
                    "body": response.json(),
                }
            )
        )


if __name__ == "__main__":
    main()
