"""Readiness/schedule checks do not claim learned-model training or deployed automation."""

import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("prefect") is None or importlib.util.find_spec("mlflow") is None,
    reason="Install the optional automation extra",
)


def test_weekly_missing_data_is_logged_not_trained(tmp_path, monkeypatch):
    """A real tracking run has a skipped readiness artifact and no fabricated model metrics."""
    import mlflow
    from mlflow.tracking import MlflowClient

    from pipelines.weekly_retraining import evaluate_weekly

    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{(tmp_path / 'tracking.db').as_posix()}")
    result = evaluate_weekly()
    assert result["status"] == "SKIPPED_DATA_NOT_READY" and result["model_promotion"] == "DISABLED"
    client = MlflowClient()
    run = client.get_run(result["mlflow_run_id"])
    assert run.info.status == "FINISHED" and run.data.metrics == {}
    assert run.data.tags["ml_value_claim"] == "NOT_ESTABLISHED"
    assert "readiness_report.json" in {
        f.path for f in client.list_artifacts(result["mlflow_run_id"])
    }
    mlflow.end_run()


def test_prefect_deployments_have_ist_schedules_without_starting_them():
    from pipelines.serve import deployments

    items = deployments()
    assert len(items) == 2
    assert [item.schedules[0].schedule.timezone for item in items] == [
        "Asia/Kolkata",
        "Asia/Kolkata",
    ]
    assert [item.schedules[0].schedule.cron for item in items] == ["0 6 * * *", "0 7 * * 0"]
