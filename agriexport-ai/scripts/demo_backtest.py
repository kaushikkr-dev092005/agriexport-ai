"""Create clearly SYNTHETIC series and run the real evaluation CLI for both targets."""

import csv
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from tests.test_forecasting import daily_series


def main() -> None:
    """Demo artifacts live under ignored data and carry SYNTHETIC provenance throughout."""
    root = Path("data/SYNTHETIC-demo")
    root.mkdir(parents=True, exist_ok=True)
    for target in ("demand", "price"):
        rows = [asdict(point) for point in daily_series(price=target == "price")]
        for row in rows:
            row["event_date"] = row["event_date"].isoformat()
            row["published_at"] = row["published_at"].isoformat()
        source = root / f"SYNTHETIC-{target}.csv"
        with source.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "src.forecasting.cli",
                "backtest",
                "--csv",
                str(source),
                "--target",
                target,
                "--origins",
                "2025-03-01T00:00:00Z",
                "2025-03-08T00:00:00Z",
                "--evaluation-cutoff",
                "2025-06-01T00:00:00Z",
                "--output",
                str(root / f"SYNTHETIC-{target}-report.json"),
            ],
            check=True,
        )
    print(
        json.dumps(
            {
                "demo": "passed",
                "label": "SYNTHETIC — NOT LIVE PERFORMANCE",
                "output_directory": str(root),
            }
        )
    )


if __name__ == "__main__":
    main()
