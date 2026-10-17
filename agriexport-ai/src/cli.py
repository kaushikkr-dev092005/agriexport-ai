"""Explicit local commands; no ingestion runs at import time."""

import argparse
import json
import logging
import os
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from src.database.repository import ingest, init_local, make_engine, seed
from src.ingestion.apeda import load_indian_csv
from src.ingestion.commerce import CommerceConnector, normalize_reports
from src.ingestion.comtrade import ComtradeConnector, normalize


def main() -> None:
    """Initialize local DB, import reviewed Indian CSV or retrieve Comtrade preview."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["init-local", "seed", "import-india", "comtrade", "import-commerce"]
    )
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--source", choices=["apeda", "commerce"], default="commerce")
    parser.add_argument("--source-url")
    parser.add_argument("--product", default="rice")
    parser.add_argument("--hs", default="1006")
    parser.add_argument("--partner", default="682")
    parser.add_argument("--reporter", default="356")
    parser.add_argument("--flow", choices=["M", "X"], default="X")
    parser.add_argument("--period", default="202401")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    raw_root = Path(os.getenv("RAW_STORAGE_PATH", "data/raw"))
    raw_root.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(os.getenv("DATABASE_URL", "sqlite:///./data/local.db"))
    if args.command == "init-local":
        if engine.dialect.name != "sqlite":
            parser.error("init-local is SQLite-only; use alembic upgrade head for PostgreSQL")
        init_local(engine)
        print("Local test schema and catalogue ready; no trade data invented.")
        return
    with Session(engine) as session, session.begin():
        seed(session)
        if args.command == "seed":
            print("Catalogue seeded")
            return
        if args.command == "import-india":
            if not args.csv or not args.source_url:
                parser.error("import-india requires --csv and --source-url")
            rows, raw = load_indian_csv(
                args.csv, args.source_url, datetime.now(UTC), raw_root, args.source
            )
        elif args.command == "import-commerce":
            if not (len(args.period) == 6 and args.period.isdigit()):
                parser.error("--period requires YYYYMM")
            period = date(int(args.period[:4]), int(args.period[4:]), 1)
            with httpx.Client(timeout=45, follow_redirects=True) as client:
                connector = CommerceConnector(client, raw_root)
                quantity = connector.fetch(args.hs, period, "2", use_cache=not args.no_cache)
                value = connector.fetch(args.hs, period, "1", use_cache=not args.no_cache)
                rows, raw = normalize_reports(
                    quantity, value, args.product, args.hs, period, [args.partner], raw_root
                )
        else:
            with httpx.Client(timeout=45) as client:
                connector = ComtradeConnector(
                    client,
                    raw_root,
                    api_key=os.getenv("COMTRADE_API_KEY", ""),
                    base_url=os.getenv(
                        "COMTRADE_BASE_URL", "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
                    ),
                )
                body, url, raw, observed = connector.fetch(
                    args.reporter,
                    args.partner,
                    args.hs,
                    args.period,
                    flow=args.flow,
                    use_cache=not args.no_cache,
                )
                rows = normalize(body, args.product, url, raw, observed)
        count = ingest(session, rows, str(raw))
        print(
            json.dumps(
                {
                    "inserted": count,
                    "raw_artifact": str(raw),
                    "status": "historical_observations_only" if rows else "no_records_returned",
                }
            )
        )


if __name__ == "__main__":
    main()
