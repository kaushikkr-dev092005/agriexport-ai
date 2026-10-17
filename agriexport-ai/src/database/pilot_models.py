"""Append-only pilot feedback, alert preferences, alerts and operational run summaries."""

from sqlalchemy import ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database.commercial_models import PrivateRecord
from src.database.models import Base


class ExporterFeedback(PrivateRecord, Base):
    """Self-reported outcome for a stored decision, never verified commercial ground truth."""

    __tablename__ = "exporter_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["decision_id", "tenant_id"],
            ["commercial_decisions.record_id", "commercial_decisions.tenant_id"],
            name="fk_feedback_decision_tenant",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_feedback_tenant_key"),
    )
    decision_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(80))


class AlertSubscription(PrivateRecord, Base):
    """Latest appended preference version per product/destination/horizon/currency."""

    __tablename__ = "alert_subscriptions"
    product_id: Mapped[str] = mapped_column(String(80))
    destination: Mapped[str] = mapped_column(String(3))


class AlertRecord(PrivateRecord, Base):
    """Internal dashboard alert only; no outbound transport is implicitly enabled."""

    __tablename__ = "alerts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["decision_id", "tenant_id"],
            ["commercial_decisions.record_id", "commercial_decisions.tenant_id"],
            name="fk_alert_decision_tenant",
        ),
        UniqueConstraint("tenant_id", "event_key", name="uq_alert_tenant_event"),
    )
    decision_id: Mapped[str] = mapped_column(String(64))
    event_key: Mapped[str] = mapped_column(String(64))


class PipelineRun(PrivateRecord, Base):
    """Private run status; no credentials, private amounts or tracebacks in the payload."""

    __tablename__ = "pipeline_runs"
