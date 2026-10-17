"""Phase 1 immutable trade foundation. Frozen schema; no application-model imports."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create reviewed phase-one tables."""
    op.create_table(
        "products",
        sa.Column("product_id", sa.String(80), primary_key=True),
        sa.Column("hs_code", sa.String(8), nullable=False),
        sa.Column("hs_revision", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=False),
    )
    op.create_table(
        "countries",
        sa.Column("country_code", sa.String(3), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
    )
    op.create_table(
        "raw_artifacts",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("storage_path", sa.String(2048), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "trade_observations",
        sa.Column("observation_id", sa.String(64), primary_key=True),
        sa.Column(
            "product_id", sa.String(80), sa.ForeignKey("products.product_id"), nullable=False
        ),
        sa.Column(
            "reporter", sa.String(3), sa.ForeignKey("countries.country_code"), nullable=False
        ),
        sa.Column("partner", sa.String(3), sa.ForeignKey("countries.country_code"), nullable=False),
        sa.Column("period", sa.Date, nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("flow", sa.String(1), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 6), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("value", sa.Numeric(28, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.String(100), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column(
            "raw_sha256", sa.String(64), sa.ForeignKey("raw_artifacts.sha256"), nullable=False
        ),
        sa.Column("availability_basis", sa.String(32), nullable=False),
        sa.Column("publication_evidence_url", sa.String(2048)),
        sa.Column("synthetic", sa.Boolean, nullable=False),
        sa.UniqueConstraint(
            "source_url",
            "product_id",
            "reporter",
            "partner",
            "period",
            "flow",
            "revision",
            "published_at",
        ),
    )
    for column in ("product_id", "partner", "published_at"):
        op.create_index(f"ix_trade_observations_{column}", "trade_observations", [column])


def downgrade() -> None:
    """Explicit rollback, never invoked automatically."""
    for table in ("trade_observations", "raw_artifacts", "countries", "products"):
        op.drop_table(table)
