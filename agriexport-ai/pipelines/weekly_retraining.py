"""Weekly readiness/evaluation tracking; never promote a model without real outcomes."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def evaluate_weekly(
    csv_path: str | None = None,
    origins: list[str] | None = None,
    evaluation_cutoff: str | None = None,
    target: str = "demand",
) -> dict:
    """Track either missing-data readiness or measured chronological baseline evaluation."""
    import mlflow

    from src.forecasting.cli import load_series
    from src.forecasting.evaluation import backtest

    if target not in {"demand", "price"}:
        raise ValueError("Supported targets: demand, price")
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "sqlite:///data/mlflow.db"))
    mlflow.set_experiment("agriexport-weekly-readiness")
    with mlflow.start_run() as run:
        mlflow.log_params(
            {
                "target": target,
                "horizons": "7,14,28",
                "model_promotion": "DISABLED_NO_VALIDATED_CANDIDATE",
            }
        )
        if csv_path is None:
            report = {
                "status": "SKIPPED_DATA_NOT_READY",
                "reason": "No verified daily outcome series configured",
                "synthetic": False,
                "trained_model": None,
                "model_promotion": "DISABLED",
            }
        else:
            if not origins or not evaluation_cutoff:
                raise ValueError(
                    "Chronological origins and an explicit evaluation cutoff are required"
                )
            cutoff = datetime.fromisoformat(evaluation_cutoff)
            if cutoff.tzinfo is None or cutoff > datetime.now(UTC):
                raise ValueError("Evaluation cutoff must be timezone-aware and no later than now")
            points = load_series(Path(csv_path))
            report = backtest(points, [datetime.fromisoformat(v) for v in origins], cutoff, target)
            report["input_sha256"] = hashlib.sha256(Path(csv_path).read_bytes()).hexdigest()
            report["model_promotion"] = "DISABLED_NO_VALIDATED_CANDIDATE"
            report["trained_model"] = None
            for segment in report["segments"]:
                for name in ("mae", "wape", "bias"):
                    if segment.get(name) is not None:
                        mlflow.log_metric(
                            f"h{segment['horizon_days']}_{segment['method']}_{name}", segment[name]
                        )
        mlflow.set_tags(
            {
                "synthetic": str(report["synthetic"]).lower(),
                "readiness": report["status"],
                "ml_value_claim": "NOT_ESTABLISHED",
            }
        )
        mlflow.log_dict(report, "readiness_report.json")
        return {
            "status": report["status"],
            "synthetic": report["synthetic"],
            "model_promotion": report["model_promotion"],
            "mlflow_run_id": run.info.run_id,
        }


def main() -> None:
    """Optional series evaluates baselines; no series means an auditable skipped training run."""
    from prefect import flow

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv")
    parser.add_argument("--origins", nargs="+")
    parser.add_argument("--evaluation-cutoff")
    parser.add_argument("--target", choices=["demand", "price"], default="demand")
    args = parser.parse_args()
    result = flow(name="agriexport-weekly", log_prints=False)(evaluate_weekly)(
        args.csv, args.origins, args.evaluation_cutoff, args.target
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
