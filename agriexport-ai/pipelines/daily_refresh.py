"""Daily public ingestion/context and tenant-scoped legal/commercial decision refresh."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.auth import Principal, load_credentials
from src.database.commercial_models import CommercialDecision, ExportCostQuote
from src.database.models import Prediction
from src.database.pilot_models import PipelineRun
from src.database.private_repository import append_record, tenant_session
from src.database.repository import make_engine
from src.forecasting.service import latest_forecasts, run_forecasts
from src.ranking.alerts import emit_alerts
from src.ranking.commercial import decide
from src.ranking.profitability import StrictModel

ROOT = Path(__file__).resolve().parents[1]


class IngestionJob(StrictModel):
    source: Literal["commerce", "comtrade"]
    product_id: str = Field(pattern=r"^[a-z_]+$")
    hs_code: str = Field(pattern=r"^\d{4,8}$")
    period: str = Field(pattern=r"^\d{6}$")
    partner: str = Field(pattern=r"^\d{3}$")
    reporter: str = Field(default="356", pattern=r"^\d{3}$")
    flow: Literal["X", "M"] = "X"


class RefreshConfig(StrictModel):
    """Empty jobs means no feed configured, never successful ingestion by assumption."""

    jobs: list[IngestionJob] = Field(default_factory=list, max_length=20)


def ingest_job(job: IngestionJob, engine: Engine) -> dict:
    """Run an existing validated connector with fixed arguments; credentials stay in env."""
    command = [
        sys.executable,
        "-m",
        "src.cli",
        "import-commerce" if job.source == "commerce" else "comtrade",
        "--product",
        job.product_id,
        "--hs",
        job.hs_code,
        "--period",
        job.period,
        "--partner",
        job.partner,
    ]
    if job.source == "comtrade":
        command += ["--reporter", job.reporter, "--flow", job.flow]
    elif job.reporter != "356" or job.flow != "X":
        raise ValueError("Commerce job supports Indian exports only")
    environment = dict(os.environ, DATABASE_URL=engine.url.render_as_string(hide_password=False))
    result = subprocess.run(
        command,
        check=False,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        timeout=150,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        return {"source": job.source, "status": "UNVERIFIED_SOURCE_FAILED"}
    payload = json.loads(result.stdout)
    return {"source": job.source, "status": payload["status"], "inserted": payload["inserted"]}


def refresh_tenant(engine: Engine, principal: Principal, now: datetime) -> dict:
    """Re-evaluate latest real quotation versions with all required gates before alerts."""
    decisions, alert_count, blocked = 0, 0, 0
    with tenant_session(engine, principal) as session:
        quotes = session.scalars(
            select(ExportCostQuote)
            .where(
                ExportCostQuote.tenant_id == principal.tenant_id,
                ExportCostQuote.synthetic.is_(False),
                ExportCostQuote.created_at <= now,
            )
            .order_by(ExportCostQuote.created_at.desc(), ExportCostQuote.record_id.desc())
        )
        latest = {}
        for quote in quotes:
            latest.setdefault(quote.payload.get("original_quote_id", quote.record_id), quote)
        for quote in latest.values():
            for horizon in (7, 14, 28):
                values = latest_forecasts(
                    session, now, quote.product_id, quote.destination, horizon
                )
                prediction = session.get(Prediction, values[0]["prediction_id"]) if values else None
                payload = decide(session, principal, quote, prediction, now, horizon)
                record = append_record(
                    session,
                    CommercialDecision,
                    principal,
                    payload,
                    "decision.daily_refresh",
                    False,
                    quote_id=quote.record_id,
                    prediction_id=prediction.prediction_id if prediction else None,
                )
                alert_count += emit_alerts(session, principal, record)
                decisions += 1
                blocked += payload["status"] == "BLOCKED_OR_UNVERIFIED"
        summary = {
            "decisions": decisions,
            "blocked": blocked,
            "alerts": alert_count,
            "blocked_share": blocked / decisions if decisions else None,
            "as_of": now.isoformat(),
            "delivery": "DASHBOARD_ONLY",
        }
    return summary


def run_daily(
    engine: Engine, config: RefreshConfig, principals: list[Principal], ingestor=ingest_job
) -> dict:
    """Persist source/tenant run status without leaking quote data into global summaries."""
    sources = []
    for job in config.jobs:
        try:
            sources.append(ingestor(job, engine))
        except (ValueError, OSError, subprocess.TimeoutExpired):
            sources.append({"source": job.source, "status": "UNVERIFIED_SOURCE_FAILED"})
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        contexts = len(run_forecasts(session, now))
    summaries = []
    for principal in principals:
        try:
            summary = refresh_tenant(engine, principal, datetime.now(UTC))
            summary["status"] = (
                "DEGRADED"
                if not sources or any(s["status"] == "UNVERIFIED_SOURCE_FAILED" for s in sources)
                else "COMPLETED_WITH_DATA_GATES"
            )
        except (ValueError, SQLAlchemyError) as error:
            summary = {"status": "FAILED", "error_type": type(error).__name__}
        with tenant_session(engine, principal) as session:
            append_record(
                session,
                PipelineRun,
                principal,
                {
                    **summary,
                    "sources": sources,
                    "forecast_contexts": contexts,
                    "feed_status": "NOT_CONFIGURED" if not sources else "SEE_SOURCE_RESULTS",
                },
                "pipeline.daily_refresh",
            )
        summaries.append(summary)
    return {
        "status": "DEGRADED"
        if not sources
        or any(s["status"] == "UNVERIFIED_SOURCE_FAILED" for s in sources)
        or any(s["status"] == "FAILED" for s in summaries)
        else "COMPLETED_WITH_DATA_GATES",
        "source_results": sources,
        "forecast_contexts": contexts,
        "tenant_runs": len(summaries),
        "weekly_model_validation": "NOT_ESTABLISHED",
        "outbound_messages": 0,
    }


def daily_refresh(config_path: str = "configs/pipeline.yaml") -> dict:
    """Entry point uses tenant metadata from the operator's environment credential registry."""
    config = RefreshConfig.model_validate(yaml.safe_load(Path(config_path).read_text()))
    tenants = {c.tenant_id for c in load_credentials().values()}
    principals = [Principal(t, "daily_refresh", frozenset({"admin"})) for t in sorted(tenants)]
    engine = make_engine(os.getenv("DATABASE_URL", "sqlite:///./data/local.db"))
    try:
        return run_daily(engine, config, principals)
    finally:
        engine.dispose()


def main() -> None:
    """A one-shot run, without starting an unattended scheduler."""
    from prefect import flow

    print(json.dumps(flow(name="agriexport-daily", log_prints=False)(daily_refresh)()))


if __name__ == "__main__":
    main()
