"""Pilot records, tenant constraints and row-level security."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None
TABLES = ("exporter_feedback", "alert_subscriptions", "alerts", "pipeline_runs")


def upgrade() -> None:
    """Create frozen pilot schema independent of mutable application models."""
    if op.get_bind().dialect.name == "postgresql":
        op.create_unique_constraint(
            "uq_commercial_decisions_record_tenant",
            "commercial_decisions",
            ["record_id", "tenant_id"],
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("commercial_decisions") as batch:
            batch.create_unique_constraint(
                "uq_commercial_decisions_record_tenant", ["record_id", "tenant_id"]
            )
    for name in TABLES:
        extra = []
        if name in {"exporter_feedback", "alerts"}:
            extra += [
                sa.Column("decision_id", sa.String(64), nullable=False),
                sa.ForeignKeyConstraint(
                    ["decision_id", "tenant_id"],
                    ["commercial_decisions.record_id", "commercial_decisions.tenant_id"],
                    name="fk_feedback_decision_tenant"
                    if name == "exporter_feedback"
                    else "fk_alert_decision_tenant",
                ),
            ]
        if name == "exporter_feedback":
            extra += [
                sa.Column("idempotency_key", sa.String(80), nullable=False),
                sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_feedback_tenant_key"),
            ]
        if name == "alerts":
            extra += [
                sa.Column("event_key", sa.String(64), nullable=False),
                sa.UniqueConstraint("tenant_id", "event_key", name="uq_alert_tenant_event"),
            ]
        if name == "alert_subscriptions":
            extra += [
                sa.Column("product_id", sa.String(80), nullable=False),
                sa.Column("destination", sa.String(3), nullable=False),
            ]
        op.create_table(
            name,
            sa.Column("record_id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON, nullable=False),
            sa.Column("synthetic", sa.Boolean, nullable=False),
            *extra,
        )
        op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"])
        op.create_index(f"ix_{name}_created_at", name, ["created_at"])
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
            op.execute(f'''CREATE POLICY tenant_isolation ON "{name}"
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))''')


def downgrade() -> None:
    """Rollback only in an explicitly isolated test database."""
    for name in reversed(TABLES):
        op.drop_table(name)
    with op.batch_alter_table("commercial_decisions") as batch:
        batch.drop_constraint("uq_commercial_decisions_record_tenant", type_="unique")
