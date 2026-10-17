"""Opt-in Prefect scheduler; importing this module never starts unattended work."""

from pipelines.daily_refresh import daily_refresh
from pipelines.weekly_retraining import evaluate_weekly


def deployments():
    """Return explicit daily/weekly IST schedules; callers decide when to serve."""
    from prefect import flow
    from prefect.schedules import Cron

    return [
        flow(name="agriexport-daily")(daily_refresh).to_deployment(
            name="daily-refresh",
            schedules=[Cron("0 6 * * *", timezone="Asia/Kolkata")],
            concurrency_limit=1,
        ),
        flow(name="agriexport-weekly")(evaluate_weekly).to_deployment(
            name="weekly-readiness",
            schedules=[Cron("0 7 * * 0", timezone="Asia/Kolkata")],
            concurrency_limit=1,
        ),
    ]


def main() -> None:
    """Keep this process and its configured Prefect server running to execute schedules."""
    from prefect import serve

    serve(*deployments())


if __name__ == "__main__":
    main()
