"""Persist versioned baseline/context runs, not invented weekly quantities."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create auditable prediction storage with explicit nullable estimates."""
    op.create_table(
        "predictions",
        sa.Column("prediction_id", sa.String(64), primary_key=True),
        sa.Column(
            "product_id", sa.String(80), sa.ForeignKey("products.product_id"), nullable=False
        ),
        sa.Column(
            "destination", sa.String(3), sa.ForeignKey("countries.country_code"), nullable=False
        ),
        sa.Column("horizon_days", sa.Integer, nullable=False),
        sa.Column("forecast_origin", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("demand_forecast", sa.Numeric(28, 6)),
        sa.Column("margin_forecast", sa.Numeric(28, 6)),
        sa.Column("confidence", sa.Numeric(8, 6)),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("synthetic", sa.Boolean, nullable=False),
        sa.CheckConstraint("horizon_days IN (7, 14, 28)", name="supported_horizon"),
    )
    op.create_index("ix_predictions_forecast_origin", "predictions", ["forecast_origin"])
    op.create_index("ix_predictions_created_at", "predictions", ["created_at"])


def downgrade() -> None:
    """Explicit isolated/test rollback; never automatically applied to production."""
    op.drop_table("predictions")
