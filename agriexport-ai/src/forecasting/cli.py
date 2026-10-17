"""Phase 2 commands: persist context snapshots or evaluate genuine daily series."""

import argparse
import csv
import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from src.database.repository import make_engine
from src.forecasting.baselines import Observation
from src.forecasting.evaluation import backtest
from src.forecasting.service import run_forecasts


def load_series(path: Path) -> list[Observation]:
    """Read strict canonical daily observations, retaining availability and synthetic markers."""
    fields = {
        "series_id",
        "event_date",
        "published_at",
        "value",
        "unit",
        "currency",
        "revision",
        "source_url",
        "frequency",
        "synthetic",
    }
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if (
            not reader.fieldnames
            or set(reader.fieldnames) != fields
            or len(reader.fieldnames) != len(fields)
        ):
            raise ValueError("Exact canonical daily-series headings required")
        result = []
        for number, row in enumerate(reader, start=2):
            if row["synthetic"].lower() not in {"true", "false"}:
                raise ValueError(f"Row {number}: synthetic must be true or false")
            result.append(
                Observation(
                    series_id=row["series_id"],
                    event_date=date.fromisoformat(row["event_date"]),
                    published_at=datetime.fromisoformat(row["published_at"]),
                    value=float(row["value"]),
                    unit=row["unit"],
                    currency=row["currency"] or None,
                    revision=row["revision"],
                    source_url=row["source_url"],
                    frequency=row["frequency"],
                    synthetic=row["synthetic"].lower() == "true",
                )
            )
    if not result:
        raise ValueError("Empty quantitative series")
    return result


def main() -> None:
    """Run explicitly; source ingestion and forecast writes never occur on API reads."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    forecast = commands.add_parser("forecast")
    forecast.add_argument("--as-of")
    forecast.add_argument("--include-synthetic", action="store_true")
    evaluate = commands.add_parser("backtest")
    evaluate.add_argument("--csv", type=Path, required=True)
    evaluate.add_argument("--origins", nargs="+", required=True)
    evaluate.add_argument("--evaluation-cutoff", required=True)
    evaluate.add_argument("--target", choices=["demand", "price"], default="demand")
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "forecast":
        origin = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
        engine = make_engine(os.getenv("DATABASE_URL", "sqlite:///./data/local.db"))
        try:
            with Session(engine) as session, session.begin():
                predictions = run_forecasts(session, origin, args.include_synthetic)
                print(
                    json.dumps(
                        {
                            "runs": len(predictions),
                            "horizons": [7, 14, 28],
                            "mode": "SEASONAL_OUTLOOK",
                            "weekly_quantities": "not_calculated",
                            "performance": "not_measured",
                            "origin": origin.isoformat(),
                        }
                    )
                )
        finally:
            engine.dispose()
    else:
        points = load_series(args.csv)
        report = backtest(
            points,
            [datetime.fromisoformat(v) for v in args.origins],
            datetime.fromisoformat(args.evaluation_cutoff),
            args.target,
        )
        report["series_id"] = points[0].series_id
        report["unit"] = points[0].unit
        report["currency"] = points[0].currency
        report["frequency"] = points[0].frequency
        report["input_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "report": str(args.output),
                    "synthetic": report["synthetic"],
                    "segments": report["segments"],
                }
            )
        )


if __name__ == "__main__":
    main()
